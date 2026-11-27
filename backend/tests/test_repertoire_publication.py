import copy
import json
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import test_repertoire_editing as base
from modules.planning.repertoire_affiche import LockRequest, UnlockRequest, unlock_affiche
from modules.planning.repertoire_publication import (preview_publication, confirm_publication, ConfirmPublication,
    require_superadmin, stop_publication)
from modules.planning.repertoire_router import get_repertoire, save_repertoire, SaveRules
from modules.planning.repertoire_search import _drafts
from modules.planning.repertoire_editing import review_draft
from modules.planning.models import RepertoireAffiche, RepertoirePublication, PlanningAssignment
from modules.calendar.models import CalendarEvent
from modules.polling.models import Poll
from modules.calendar.services import CalendarService
from modules.planning.repertoire_source import load_snapshot, get_rules
from modules.planning.router import router
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient


class RepertoirePublicationTests(unittest.TestCase):
    answer = base.RepertoireEditingTests.answer
    request = base.RepertoireEditingTests.request
    review = base.RepertoireEditingTests.review

    def setUp(self):
        base.RepertoireEditingTests.setUp(self)
        self.http = SimpleNamespace(state=SimpleNamespace(is_superadmin=True, telegram_user=SimpleNamespace(id=42)))
        self.events = {'rep': {'id': 'rep', 'etag': 'v1', 'summary': 'Урод [Реп]', 'location': 'Зал', 'description': 'Описание',
            'recurringEventId': 'series', 'start': {'dateTime': '2028-10-07T17:00:00+03:00'}, 'end': {'dateTime': '2028-10-07T18:00:00+03:00'}}}
        self.google = MagicMock()
        self.google.patch_event.side_effect = self.patch_event
        self.google.ensure_planned_event.side_effect = self.create_event
        for target, value in [('google_client', self.google), ('local_now', datetime(2028, 9, 1))]:
            p = patch('modules.planning.repertoire_publication.' + target, return_value=value); p.start(); self.addCleanup(p.stop)
        p = patch('modules.planning.repertoire_affiche.local_now', return_value=datetime(2028, 9, 1)); p.start(); self.addCleanup(p.stop)
        p = patch('modules.planning.repertoire_publication.month_events', side_effect=self.list_events); p.start(); self.addCleanup(p.stop)
        CalendarService(self.db, self.google).sync_from_google(self.list_events(self.google, '2028-10'))

    def tearDown(self):
        base.RepertoireEditingTests.tearDown(self)

    def list_events(self, google, month):
        from core.time import as_local
        google.sync_window = (as_local(datetime(2028, 10, 1)), as_local(datetime(2028, 11, 1)))
        return copy.deepcopy(list(self.events.values()))

    def patch_event(self, calendar, id, body, etag):
        self.assertEqual(self.events[id]['etag'], etag)
        self.events[id].update(copy.deepcopy(body)); self.events[id]['etag'] = 'new'
        return copy.deepcopy(self.events[id])

    def create_event(self, calendar, id, body):
        self.events.setdefault(id, {'id': id, 'etag': 'created', **copy.deepcopy(body)})
        return copy.deepcopy(self.events[id])

    def preview(self, entries=None):
        reviewed = self.review(entries if entries is not None else [('2028-10-07', 'catalog:2'), ('2028-10-14', 'catalog:1')])
        request = LockRequest(month='2028-10', search_id=reviewed['search_id'], variant_id=reviewed['variant']['id'],
            expected_fingerprint=reviewed['fingerprint'], expected_revision=reviewed['revision'])
        return preview_publication(request, self.http, self.db)

    def confirm(self, preview):
        return confirm_publication(ConfirmPublication(preview_id=preview['id'], choices={'2028-10-07': 'rep'}, locations={'2028-10-14': 'Новый зал'}), self.http, self.db)

    def test_preview_does_not_write_google_and_confirmation_renames_one_instance_creates_free_day(self):
        preview = self.preview()
        self.assertEqual([a['kind'] for a in preview['actions']], ['replace', 'create'])
        self.google.patch_event.assert_not_called(); self.google.ensure_planned_event.assert_not_called()
        result = self.confirm(preview)
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(self.events['rep']['summary'], 'Другой [Спект]')
        self.assertEqual(self.events['rep']['start']['dateTime'][11:16], '19:00')
        self.assertEqual(self.events['rep']['description'], 'Описание')
        self.assertEqual(self.events['rep']['recurringEventId'], 'series')
        self.assertEqual(len(self.events), 2)
        self.assertEqual(self.db.query(CalendarEvent).count(), 2)
        self.assertEqual(self.db.query(PlanningAssignment).count(), 0)
        self.client.ensure_schedule_columns.assert_not_called()
        # Duplicated confirmation and process-cache loss cannot create another event.
        self.confirm(preview)
        self.assertEqual(self.google.patch_event.call_count, 1)
        self.assertEqual(self.google.ensure_planned_event.call_count, 1)
        for job in _drafts.values(): job['generator'].close()
        _drafts.clear(); self.db.expire_all()
        saved = get_repertoire('2028-10', page=0, db=self.db)
        self.assertTrue(saved['locked']); self.assertIsNone(saved['lock_error'])
        self.assertEqual(len(saved['variants']), 1)
        self.assertEqual([e['date'] for e in saved['variants'][0]['entries']], ['2028-10-07', '2028-10-14'])
        self.assertTrue(all(not e['cast'] for e in saved['variants'][0]['entries']))
        stored = json.loads(self.db.get(RepertoireAffiche, '2028-10').payload)
        self.assertTrue(all(not e['cast'] for e in stored['entries']))
        # Old audit payloads must not turn provisional solver choices into assignments.
        old = self.db.get(RepertoirePublication, preview['id'])
        payload = json.loads(old.payload)
        for entry in payload['variant']['entries']:
            entry['cast'] = {'Роль': 'Анна'}
        old.payload = json.dumps(payload); self.db.commit()
        source = load_snapshot(self.db, self.client, '2028-10', fresh=True)
        self.assertTrue(all(not e['cast'] for e in source['fixed']))
        preview_req = self.request([])
        with self.assertRaises(HTTPException): review_draft(preview_req, self.db)
        unlock_affiche(UnlockRequest(month='2028-10', expected_revision=saved['revision']), self.http, self.db)
        self.assertEqual(len(self.events), 2)
        self.assertIsNone(self.db.get(RepertoireAffiche, '2028-10'))

    def test_empty_draft_stays_empty_and_partial_goal_does_not_get_refilled(self):
        preview = self.preview([])
        self.assertEqual(preview['actions'], [])
        self.confirm(preview)
        plan = get_repertoire('2028-10', page=0, db=self.db)
        self.assertEqual(plan['variants'][0]['entries'], [])
        self.assertEqual(plan['maximum'], 0)
        self.google.patch_event.assert_not_called(); self.google.ensure_planned_event.assert_not_called()

    def test_missing_choice_or_location_requires_review_before_any_write(self):
        preview = self.preview()
        for request in (ConfirmPublication(preview_id=preview['id']), ConfirmPublication(preview_id=preview['id'], choices={'2028-10-07': 'rep'})):
            with self.assertRaises(HTTPException) as error: confirm_publication(request, self.http, self.db)
            self.assertEqual(error.exception.status_code, 422)
        self.google.patch_event.assert_not_called(); self.google.ensure_planned_event.assert_not_called()

    def test_reopening_same_preview_renews_confirmation_expiry(self):
        preview = self.preview([])
        row = self.db.get(RepertoirePublication, preview['id'])
        row.created_at = datetime.utcnow() - timedelta(hours=1); self.db.commit()
        with self.assertRaises(HTTPException): self.confirm(preview)
        fresh = self.preview([])
        self.assertEqual(fresh['id'], preview['id'])
        self.assertEqual(self.confirm(fresh)['status'], 'complete')

    def test_multi_day_rehearsal_is_not_silently_shortened(self):
        self.events['rep']['end'] = {'dateTime': '2028-10-08T20:00:00+03:00'}
        CalendarService(self.db, self.google).sync_from_google(self.list_events(self.google, '2028-10'))
        with self.assertRaises(HTTPException) as error: self.preview()
        self.assertIn('несколько дней', error.exception.detail)
        self.google.patch_event.assert_not_called()

    def test_multiple_rehearsals_replace_only_explicitly_selected_occurrence(self):
        self.events['other'] = {**copy.deepcopy(self.events['rep']), 'id': 'other', 'summary': 'Другой [Реп]'}
        CalendarService(self.db, self.google).sync_from_google(self.list_events(self.google, '2028-10'))
        preview = self.preview([('2028-10-07', 'catalog:2')])
        self.assertEqual(len(preview['actions'][0]['targets']), 2)
        self.confirm(preview)
        self.assertEqual(self.events['other']['summary'], 'Другой [Реп]')
        self.assertEqual(self.events['rep']['summary'], 'Другой [Спект]')
        self.assertEqual(self.google.patch_event.call_count, 1)

    def test_lost_create_response_is_reconciled_without_duplicate(self):
        preview = self.preview([('2028-10-14', 'catalog:1')])
        def lost(*args):
            self.create_event(*args)
            raise TimeoutError('lost insert response')
        self.google.ensure_planned_event.side_effect = lost
        self.assertEqual(self.confirm(preview)['status'], 'partial')
        self.google.ensure_planned_event.side_effect = self.create_event
        self.assertEqual(self.confirm(preview)['status'], 'complete')
        self.assertEqual(self.google.ensure_planned_event.call_count, 1)
        self.assertEqual(len(self.events), 2)

    def test_all_day_rehearsal_becomes_timed_show(self):
        self.events['rep']['start'] = {'date': '2028-10-07'}
        self.events['rep']['end'] = {'date': '2028-10-08'}
        CalendarService(self.db, self.google).sync_from_google(self.list_events(self.google, '2028-10'))
        preview = self.preview([('2028-10-07', 'catalog:2')])
        self.assertEqual(self.confirm(preview)['status'], 'complete')
        body = self.google.patch_event.call_args.args[2]
        self.assertIsNone(body['start']['date'])
        self.assertEqual(body['start']['dateTime'][11:16], '19:00')

    def test_changed_votes_or_external_event_reject_before_first_write(self):
        preview = self.preview()
        self.answer('2028-10-14', 'no')
        with self.assertRaises(HTTPException): self.confirm(preview)
        self.answer('2028-10-14', 'yes')
        preview = self.preview()
        self.events['rep']['etag'] = 'external'
        with self.assertRaises(HTTPException): self.confirm(preview)
        self.google.patch_event.assert_not_called(); self.google.ensure_planned_event.assert_not_called()

    def test_lost_patch_response_resumes_without_repeating_write(self):
        preview = self.preview()
        def lost(*args):
            self.patch_event(*args)
            raise TimeoutError('lost response')
        self.google.patch_event.side_effect = lost
        result = self.confirm(preview)
        self.assertEqual(result['status'], 'partial')
        self.assertIsNone(self.db.get(RepertoireAffiche, '2028-10'))
        plan = get_repertoire('2028-10', page=0, db=self.db)
        self.assertEqual(plan['publication']['id'], preview['id'])
        self.google.patch_event.side_effect = self.patch_event
        result = self.confirm(preview)
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(self.google.patch_event.call_count, 1)
        self.assertEqual(len(self.events), 2)

    def test_partial_can_be_stopped_without_undo_or_replay(self):
        preview = self.preview()
        self.google.ensure_planned_event.side_effect = TimeoutError('offline')
        self.assertEqual(self.confirm(preview)['status'], 'partial')
        result = stop_publication(ConfirmPublication(preview_id=preview['id']), self.db)
        self.assertEqual(result['status'], 'stopped')
        self.assertEqual(self.events['rep']['summary'], 'Другой [Спект]')
        with self.assertRaises(HTTPException): self.confirm(preview)
        self.assertIsNone(get_repertoire('2028-10', page=0, db=self.db)['publication'])

    def test_superadmin_gate_for_preview_confirm_unlock_and_stop(self):
        app = FastAPI(); app.include_router(router)
        @app.middleware('http')
        async def admin_only(request, call_next):
            request.state.is_admin = True; request.state.is_superadmin = False
            return await call_next(request)
        with TestClient(app) as client:
            for path in ('/lock/preview', '/lock', '/lock/stop'):
                self.assertEqual(client.post('/api/planning/repertoire' + path, json={}).status_code, 403)
            self.assertEqual(client.post('/api/planning/repertoire/unlock', json={'month': '2028-10', 'expected_revision': 0}).status_code, 403)
        self.google.patch_event.assert_not_called()
