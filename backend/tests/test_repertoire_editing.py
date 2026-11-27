import unittest
from datetime import date, datetime
from unittest.mock import patch

import test_repertoire as base
from modules.planning.repertoire_editing import DraftRequest, review_draft, day_choices
from modules.planning.repertoire_source import load_snapshot, get_rules
from modules.planning.repertoire import digest
from modules.planning.repertoire_search import cached_variant, _drafts
from modules.planning.repertoire_sharing import prepare_preview, PreviewRequest
from modules.planning.models import RepertoireSettings, PlanningAssignment
from modules.planning.router import router, AssignRequest
from modules.planning.repertoire_router import validate_review
from modules.theater.models import TheaterShow
from modules.calendar.models import CalendarEvent
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError


class RepertoireEditingTests(unittest.TestCase):
    answer = base.RepertoireSourceTests.answer

    def setUp(self):
        base.RepertoireSourceTests.setUp(self)
        self.db.add(TheaterShow(id=2, name='Другой', normalized_name='другой'))
        self.db.commit()
        self.source['casts'].append(['Другой', 'Роль', 'Анна'])
        for day in ('2028-10-07', '2028-10-08', '2028-10-09', '2028-10-14'):
            self.answer(day, 'yes')
        for target in ('modules.planning.repertoire_editing.local_now', 'modules.planning.repertoire_router.local_now', 'modules.planning.repertoire_sharing.local_now'):
            patcher = patch(target, return_value=datetime(2028, 9, 1)); patcher.start(); self.addCleanup(patcher.stop)
        patcher = patch('modules.planning.repertoire_router.snapshot', side_effect=lambda db, month, **kwargs: load_snapshot(db, self.client, month, fresh=True))
        patcher.start(); self.addCleanup(patcher.stop)
        for job in _drafts.values():
            job['generator'].close()
        _drafts.clear()

    def tearDown(self):
        base.RepertoireSourceTests.tearDown(self)

    def request(self, entries):
        source = load_snapshot(self.db, self.client, '2028-10', fresh=True)
        _, revision, _ = get_rules(self.db, '2028-10', source['shows'])
        return DraftRequest(month='2028-10', entries=[{'day': d, 'key': k} for d, k in entries],
            expected_fingerprint=source['fingerprint'], expected_revision=revision)

    def review(self, entries):
        req = self.request(entries)
        for _ in range(10):
            result = review_draft(req, self.db)
            if result['status'] != 'calculating':
                return result
        self.fail('Simple draft did not finish')

    def test_empty_date_lists_all_shows_including_zero_goal_with_role_answers(self):
        result = day_choices('2028-10', date(2028, 10, 7), self.db)
        self.assertEqual({s['name'] for s in result['shows']}, {'Урод', 'Другой'})
        for show in result['shows']:
            self.assertIsNone(show['reason'])
            self.assertEqual(show['votes'], {'yes': 1, 'no': 0, 'unknown': 0, 'unanswered': 0, 'other': 0})
            self.assertEqual(show['covered'], 1)
            self.assertEqual(show['roles'][0]['actors'][0]['name'], 'Анна')
        self.assertEqual(self.db.query(PlanningAssignment).count(), 0)

    def test_day_exposes_existing_planner_cell_without_creating_sheet_columns(self):
        result = day_choices('2028-10', date(2028, 10, 7), self.db)
        source = load_snapshot(self.db, self.client, '2028-10', fresh=True)
        slot = next(s for s in source['slots'] if s['date'] == result['day'])
        self.assertEqual(result['planning_slot']['label'], slot['label'])
        self.assertNotIn('column', result['planning_slot'])
        for show in result['shows']:
            original = next(c for c in slot['shows'] if c['key'] == show['key'])
            for key in ('roles', 'status', 'suggested_cast', 'incomplete'):
                self.assertEqual(show['planning_cell'][key], original[key])
            self.assertIn('attendance', show['planning_cell'])
        self.client.ensure_schedule_columns.assert_not_called()

    def test_unanswered_date_still_lists_votes_and_disables_show(self):
        result = day_choices('2028-10', date(2028, 10, 20), self.db)
        self.assertEqual(len(result['shows']), 2)
        self.assertTrue(all(s['reason'] and s['votes']['other'] == 1 for s in result['shows']))

    def test_day_votes_are_live_unique_answers_not_role_assignments(self):
        self.source['casts'].append(['Урод', 'Вторая роль', 'Анна'])
        self.source['schedule'] = [['Актёр', '7 окт 2028'], ['', 'Урод'], ['Анна', 'Летте']]
        for value, bucket in [('yes', 'yes'), ('no', 'no'), ('unknown', 'unknown'), ('retracted', 'unanswered')]:
            self.answer('2028-10-07', value)
            selected = next(s for s in day_choices('2028-10', date(2028, 10, 7), self.db)['shows'] if s['key'] == 'catalog:1')
            self.assertEqual(selected['votes'][bucket], 1)
            self.assertEqual(sum(selected['votes'][k] for k in ('yes', 'no', 'unknown', 'unanswered')), 1)
            self.assertEqual(selected['covered'], 1 if value == 'yes' else 0)

    def test_exact_replacement_retains_other_date_and_exposes_shortfall_and_excess(self):
        result = self.review([('2028-10-07', 'catalog:2'), ('2028-10-14', 'catalog:1')])
        variant = result['variant']
        self.assertTrue(variant['manual'])
        self.assertNotEqual(variant['id'], digest([(e['date'], e['key']) for e in variant['entries']]))
        self.assertEqual([(e['date'], e['key']) for e in variant['entries']], [('2028-10-07', 'catalog:2'), ('2028-10-14', 'catalog:1')])
        self.assertEqual(variant['missing'], [{'key': 'catalog:1', 'name': 'Урод', 'count': 1}])
        self.assertEqual(variant['excess'], [{'key': 'catalog:2', 'name': 'Другой', 'count': 1}])
        self.assertEqual(cached_variant(result['search_id'], variant['id']), variant)
        self.assertEqual(self.db.query(RepertoireSettings).count(), 0)
        self.assertEqual(self.db.query(PlanningAssignment).count(), 0)
        self.client.ensure_schedule_columns.assert_not_called()

    def test_changed_vote_and_forged_date_cannot_be_applied(self):
        req = self.request([('2028-10-07', 'catalog:2')])
        self.answer('2028-10-07', 'no')
        with self.assertRaises(HTTPException) as error:
            review_draft(req, self.db)
        self.assertEqual(error.exception.status_code, 409)
        with self.assertRaises(HTTPException):
            self.review([('2028-10-07', 'catalog:2')])
        with self.assertRaises(HTTPException):
            self.review([('2028-11-07', 'catalog:2')])
        with self.assertRaises(ValidationError):
            self.request([('2028-10-07', 'catalog:1'), ('2028-10-07', 'catalog:2')])

    def test_evening_conflicts_remain_hard_constraints(self):
        self.db.add(CalendarEvent(google_event_id='rent', title='Аренда', start_time=datetime(2028, 10, 7, 18), end_time=datetime(2028, 10, 7, 21)))
        self.db.commit()
        day = day_choices('2028-10', date(2028, 10, 7), self.db)
        self.assertTrue(all('Пересечение' in s['reason'] for s in day['shows']))
        with self.assertRaises(HTTPException):
            self.review([('2028-10-07', 'catalog:2')])

    def test_existing_show_cannot_be_replaced_and_is_retained_in_manual_draft(self):
        self.db.add(CalendarEvent(google_event_id='show', title='Урод [Спект]', start_time=datetime(2028, 10, 7, 19), end_time=datetime(2028, 10, 7, 20, 30)))
        self.db.commit()
        with self.assertRaises(HTTPException):
            self.review([('2028-10-07', 'catalog:2')])
        result = self.review([('2028-10-14', 'catalog:2')])
        self.assertTrue(result['variant']['entries'][0]['fixed'])
        self.assertEqual(result['variant']['entries'][0]['date'], '2028-10-07')
        refreshed = self.review([('2028-10-07', 'catalog:1'), ('2028-10-14', 'catalog:2')])
        self.assertEqual(len(refreshed['variant']['entries']), 2)
        self.assertTrue(refreshed['variant']['entries'][0]['fixed'])

    def test_pins_cannot_be_silently_replaced_or_removed(self):
        source = load_snapshot(self.db, self.client, '2028-10', fresh=True)
        rules, _, _ = get_rules(self.db, '2028-10', source['shows'])
        from modules.planning.repertoire import Pin
        rules.pins = [Pin(day='2028-10-07', key='catalog:1')]
        self.db.add(RepertoireSettings(month='2028-10', revision=1, payload=rules.model_dump_json())); self.db.commit()
        with self.assertRaises(HTTPException):
            self.review([('2028-10-14', 'catalog:1')])
        choices = day_choices('2028-10', date(2028, 10, 7), self.db)
        self.assertIn('закреплён', next(s for s in choices['shows'] if s['key'] == 'catalog:2')['reason'])
        result = self.review([('2028-10-07', 'catalog:1'), ('2028-10-14', 'catalog:2')])
        self.assertEqual(len(result['variant']['entries']), 2)

    def test_forbidden_load_blocks_change_while_soft_load_warns(self):
        entries = [('2028-10-07', 'catalog:1'), ('2028-10-08', 'catalog:2'), ('2028-10-09', 'catalog:1')]
        result = self.review(entries)
        self.assertEqual(result['variant']['load_warnings'][0]['actor'], 'Анна')
        source = load_snapshot(self.db, self.client, '2028-10', fresh=True)
        rules, _, _ = get_rules(self.db, '2028-10', source['shows']); rules.load_mode = 'forbid'
        self.db.add(RepertoireSettings(month='2028-10', revision=1, payload=rules.model_dump_json())); self.db.commit()
        with self.assertRaises(HTTPException):
            self.review(entries)

    def test_manual_variant_can_be_previewed_and_zero_goal_show_assigned_after_review(self):
        result = self.review([('2028-10-07', 'catalog:2')])
        req = PreviewRequest(month='2028-10', search_id=result['search_id'], variant_id=result['variant']['id'],
            chat_id=-100123, expected_fingerprint=result['fingerprint'], expected_revision=result['revision'])
        preview = prepare_preview(req, 42, 'Тестовый чат', self.db)
        self.assertIn('Другой', preview['text'])
        self.assertIn('ручными заменами', preview['text'])
        self.assertIn('Сверх плана', preview['text'])
        assignment = AssignRequest(month='2028-10', column='B', show_name='Другой', cast={'Роль': 'Анна'},
            expected_fingerprint='sheet', start_time='2028-10-07T19:00', end_time='2028-10-07T20:30', location='Зал',
            repertoire={'key': 'catalog:2', 'fingerprint': result['fingerprint'], 'revision': result['revision']})
        validate_review(self.db, self.client, assignment, date(2028, 10, 7))

    def test_day_and_manual_draft_routes_inherit_admin_guard(self):
        app = FastAPI(); app.include_router(router)
        with TestClient(app) as client:
            self.assertEqual(client.get('/api/planning/repertoire/day?month=2028-10&day=2028-10-07').status_code, 403)
            self.assertEqual(client.post('/api/planning/repertoire/draft', json={}).status_code, 403)
