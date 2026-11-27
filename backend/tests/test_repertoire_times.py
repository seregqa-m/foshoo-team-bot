import json
import unittest
from datetime import date, datetime

import test_repertoire_editing as editing
import test_repertoire_publication as publication
from fastapi import HTTPException
from pydantic import ValidationError
from modules.planning.repertoire import DraftEntry
from modules.planning.repertoire_editing import review_draft
from modules.planning.repertoire_source import load_snapshot
from modules.planning.repertoire_sharing import prepare_preview, PreviewRequest
from modules.planning.repertoire_affiche import LockRequest, locked_result
from modules.planning.repertoire_publication import preview_publication
from modules.planning.repertoire_router import get_repertoire
from modules.planning.models import RepertoireAffiche
from modules.calendar.models import CalendarEvent


def change_time(test, clock, other=True):
    req = test.request([('2028-10-07', 'catalog:1')] + ([('2028-10-14', 'catalog:1')] if other else []))
    req.entries[0].start_time = clock
    for _ in range(10):
        result = review_draft(req, test.db)
        if result['status'] != 'calculating':
            return result
    test.fail('Draft validation did not finish')


class RepertoireTimeTests(unittest.TestCase):
    setUp = editing.RepertoireEditingTests.setUp
    tearDown = editing.RepertoireEditingTests.tearDown
    answer = editing.RepertoireEditingTests.answer
    request = editing.RepertoireEditingTests.request

    def test_one_show_day_changes_without_changing_other_dates_or_automatic_defaults(self):
        changed = change_time(self, '18:45')
        entries = changed['variant']['entries']
        self.assertEqual([(e['date'], e['start_time'][11:16], e['end_time'][11:16]) for e in entries],
                         [('2028-10-07', '18:45', '20:15'), ('2028-10-14', '19:00', '20:30')])
        later = change_time(self, '20:00')
        self.assertNotEqual(changed['variant']['id'], later['variant']['id'])
        self.assertEqual(change_time(self, '18:45')['variant']['id'], changed['variant']['id'])
        automatic = get_repertoire('2028-10', page=0, db=self.db)
        self.assertTrue(all(e['start_time'][11:16] == ('18:00' if date.fromisoformat(e['date']).weekday() == 6 else
            '20:00' if date.fromisoformat(e['date']).weekday() < 4 else '19:00')
            for v in automatic['variants'] for e in v['entries'] if not e['fixed']))
        preview = prepare_preview(PreviewRequest(month='2028-10', search_id=changed['search_id'], variant_id=changed['variant']['id'],
            chat_id=-1001234567890, expected_fingerprint=changed['fingerprint'], expected_revision=changed['revision']), 42, 'Театр', self.db)
        self.assertIn('в 18:45 — Урод', preview['text'])
        self.assertIn('в 19:00 — Урод', preview['text'])

    def test_custom_time_rechecks_conflicts_and_can_free_a_default_time_conflict(self):
        self.db.add(CalendarEvent(title='Аренда', google_event_id='busy',
            start_time=datetime.fromisoformat('2028-10-07T19:00:00+03:00'), end_time=datetime.fromisoformat('2028-10-07T22:00:00+03:00')))
        self.db.commit()
        with self.assertRaises(HTTPException) as error:
            change_time(self, '19:00')
        self.assertIn('Пересечение', error.exception.detail)
        self.assertEqual(change_time(self, '17:30')['variant']['entries'][0]['end_time'][11:16], '19:00')
        with self.assertRaises(HTTPException):
            change_time(self, '17:31')

    def test_time_does_not_allow_missing_cast_or_overnight_answers(self):
        with self.assertRaises(HTTPException) as error:
            change_time(self, '23:00')
        self.assertIn('полуночи', error.exception.detail)
        self.answer('2028-10-07', 'no')
        with self.assertRaises(HTTPException):
            change_time(self, '18:00')
        for invalid in ('25:00', '18:60', '9:00', '19:00:00', '2028-10-07T19:00', ''):
            with self.assertRaises(ValidationError):
                DraftEntry(day='2028-10-07', key='catalog:1', start_time=invalid)

    def test_saved_manual_affiche_keeps_its_custom_time_on_review(self):
        changed = change_time(self, '18:45')
        source = load_snapshot(self.db, self.client, '2028-10', fresh=True)
        rules, _, _ = editing.get_rules(self.db, '2028-10', source['shows'])
        row = RepertoireAffiche(month='2028-10', payload=json.dumps(changed['variant']))
        result = locked_result(row, source, rules)
        self.assertIsNone(result['lock_error'])
        self.assertEqual(result['variants'][0]['entries'][0]['start_time'][11:16], '18:45')


class RepertoireTimePublicationTests(unittest.TestCase):
    setUp = publication.RepertoirePublicationTests.setUp
    tearDown = publication.RepertoirePublicationTests.tearDown
    answer = publication.RepertoirePublicationTests.answer
    request = publication.RepertoirePublicationTests.request
    list_events = publication.RepertoirePublicationTests.list_events
    patch_event = publication.RepertoirePublicationTests.patch_event
    create_event = publication.RepertoirePublicationTests.create_event

    def test_calendar_publication_and_locked_readback_keep_reviewed_time(self):
        changed = change_time(self, '18:45', other=False)
        preview = preview_publication(LockRequest(month='2028-10', search_id=changed['search_id'], variant_id=changed['variant']['id'],
            expected_fingerprint=changed['fingerprint'], expected_revision=changed['revision']), self.http, self.db)
        self.assertEqual(preview['actions'][0]['start_time'][11:16], '18:45')
        from modules.planning.repertoire_publication import confirm_publication, ConfirmPublication
        result = confirm_publication(ConfirmPublication(preview_id=preview['id'], choices={'2028-10-07': 'rep'}), self.http, self.db)
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(self.events['rep']['start']['dateTime'][11:16], '18:45')
        saved = get_repertoire('2028-10', page=0, db=self.db)
        self.assertTrue(saved['locked'])
        self.assertEqual(saved['variants'][0]['entries'][0]['start_time'][11:16], '18:45')
        with self.assertRaises(HTTPException):
            change_time(self, '20:00', other=False)
