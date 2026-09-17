import copy
import os
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

with patch.dict(os.environ, {'BOT_TOKEN': '123456:offline-test-token', 'DATABASE_URL': 'sqlite://', 'GOOGLE_CALENDAR_JSON': '/missing'}, clear=True), patch('dotenv.load_dotenv'):
    from core.database import Base
    from sheets_client import SheetsClient, _parse_header_date, _format_schedule_header
    from modules.planning.services import build_plan, assignment_updates, match_roles
    from modules.planning.router import AssignRequest, assign_show, require_admin
    from modules.planning.models import PlanningAssignment
    from modules.calendar.models import CalendarEvent
    from modules.calendar.google_client import GoogleCalendarClient
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from googleapiclient.errors import HttpError
from httplib2 import Response


def fixture():
    return {
        'casts': [['Спектакль', 'Роль', 'Актёр'], ['Урод', 'Летте', 'Анна'], ['Урод', 'Летте', 'Борис'], ['Урод', 'Фанни', 'Анна']],
        'schedule': [['Актёр', '[чт] 1 окт 2028', '[пт] 2 окт 2028', '[сб] 3 окт 2028'], ['', '', '', ''],
                     ['Анна', 'да', 'да', ''], ['Борис', 'да', 'нет', 'да']],
    }


class PlanningTests(unittest.TestCase):
    def test_matching_uses_alternates_without_reusing_actor(self):
        plan = build_plan(fixture(), '2028-10')
        ready, blocked, waiting = [s['shows'][0] for s in plan['slots']]
        self.assertEqual(ready['suggested_cast'], {'Летте': 'Борис', 'Фанни': 'Анна'})
        self.assertEqual(ready['status'], 'ready')
        self.assertEqual(blocked['status'], 'blocked')  # Anna cannot play both roles.
        self.assertEqual(waiting['status'], 'waiting')  # A missing answer is not a yes.

    def test_duplicate_names_roles_missing_roster_and_unknown_values_never_fake_readiness(self):
        for change in ('duplicate_row', 'missing_role', 'unknown_value'):
            source = fixture()
            if change == 'duplicate_row': source['schedule'].append(['Анна', 'да'])
            if change == 'missing_role': source['casts'].append(['Урод', '', 'Вера'])
            if change == 'unknown_value': source['schedule'][2][1] = 'возможно'
            self.assertNotEqual(build_plan(source, '2028-10')['slots'][0]['shows'][0]['status'], 'ready')
        source = fixture(); source['casts'].append(['урод', ' летте ', 'Борис'])
        self.assertEqual(build_plan(source, '2028-10')['slots'][0]['shows'][0]['total'], 2)

    def test_assignment_writes_exact_cast_and_rejects_double_role_or_unknown_actor(self):
        source = fixture(); plan = build_plan(source, '2028-10')
        updates = assignment_updates(source, plan, 'B', 'Урод', {'Летте': 'Борис', 'Фанни': 'Анна'})
        self.assertEqual(updates, [
            {'range': "'График [составы]'!B2", 'values': [['УРОД']]},
            {'range': "'График [составы]'!B4", 'values': [['Летте']]},
            {'range': "'График [составы]'!B3", 'values': [['Фанни']]},
        ])
        for cast in ({'Летте': 'Анна', 'Фанни': 'Анна'}, {'Летте': 'Вера', 'Фанни': 'Анна'}, {'Летте': 'Борис'}):
            with self.assertRaises(ValueError): assignment_updates(source, plan, 'B', 'Урод', cast)

    def test_existing_role_assignments_are_not_treated_as_unknown_or_free_for_other_roles(self):
        source = fixture(); source['schedule'][1][1] = 'УРОД'; source['schedule'][2][1] = 'Фанни'; source['schedule'][3][1] = 'Летте'
        cell = build_plan(source, '2028-10')['slots'][0]['shows'][0]
        self.assertEqual(cell['status'], 'ready')
        self.assertEqual(cell['suggested_cast'], {'Летте': 'Борис', 'Фанни': 'Анна'})
        with self.assertRaises(ValueError): assignment_updates(source, build_plan(source, '2028-10'), 'B', 'Урод', cell['suggested_cast'])

    def test_dates_without_time_explicit_years_and_leap_day(self):
        self.assertEqual(_parse_header_date('[сб] 29 фев', 2028), datetime(2028, 2, 29))
        self.assertEqual(_parse_header_date('[чт] 1 окт 2028\n19:30', 2026), datetime(2028, 10, 1, 19, 30))
        self.assertIsNone(_parse_header_date('31 фев 2028'))
        self.assertEqual(_parse_header_date(_format_schedule_header(datetime(2028, 10, 1))), datetime(2028, 10, 1))
        self.assertEqual(build_plan(fixture(), '2027-10')['slots'], [])
        source = fixture(); source['schedule'][0][1] = '[чт] 1 окт'
        self.assertTrue(build_plan(source, '2028-10')['warnings'])

    def test_poll_answer_finds_new_date_only_headers_without_duplicate_column(self):
        client = SheetsClient.__new__(SheetsClient); client.api = MagicMock(); client.spreadsheet_id = 'test'
        client.api.values.return_value.get.return_value.execute.return_value = {'values': [['', '[чт] 1 окт 2028']]}
        client.get_show_names = MagicMock(return_value=[])
        target = datetime(2028, 10, 1)
        self.assertEqual(client.find_date_column(target), 'B')
        self.assertEqual(client.check_dates_exist([target]), [])
        self.assertEqual(client.ensure_schedule_columns([(target, '')]), 0)
        self.assertIsNone(client.find_date_column(datetime(2027, 10, 1)))
        client.api.values.return_value.update.assert_not_called()

    def test_non_admin_cannot_open_planner(self):
        with self.assertRaises(HTTPException): require_admin(SimpleNamespace(state=SimpleNamespace(is_admin=False)))


class PlanningSaveTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://'); Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.source = fixture()
        self.client = MagicMock(); self.client.spreadsheet_id = 'test'
        self.client.get_planning_data.side_effect = lambda: copy.deepcopy(self.source)
        self.google = MagicMock()
        self.req = AssignRequest(month='2028-10', column='B', show_name='Урод', cast={'Летте': 'Борис', 'Фанни': 'Анна'},
            expected_fingerprint=build_plan(self.source, '2028-10')['fingerprint'], start_time='2028-10-01T19:00:00', end_time='2028-10-01T21:00:00', location='Зал')
        self.patches = [patch('modules.planning.router.GOOGLE_CALENDAR_ID', 'calendar'), patch('modules.planning.router.get_client', return_value=self.client), patch('modules.planning.router.GoogleCalendarClient', return_value=self.google)]
        for p in self.patches: p.start()
    def tearDown(self):
        for p in reversed(self.patches): p.stop()
        self.db.close(); self.engine.dispose()

    def test_assign_and_replay_does_not_repeat_calendar_or_sheet_write(self):
        assign_show(self.req, self.db); assign_show(self.req, self.db)
        self.google.ensure_planned_event.assert_called_once()
        self.client.api.values.return_value.batchUpdate.assert_called_once()
        self.assertEqual(self.db.query(CalendarEvent).count(), 1)
        self.assertEqual(self.db.query(PlanningAssignment).one().status, 'complete')

    def test_changed_votes_rejected_before_external_writes(self):
        self.source['schedule'][2][1] = 'нет'
        with self.assertRaises(HTTPException) as exc: assign_show(self.req, self.db)
        self.assertEqual(exc.exception.status_code, 409)
        self.google.ensure_planned_event.assert_not_called()

    def test_partial_save_can_resume_and_uses_same_google_id(self):
        self.client.api.values.return_value.batchUpdate.return_value.execute.side_effect = [RuntimeError('timeout'), {}]
        with self.assertRaises(HTTPException): assign_show(self.req, self.db)
        self.assertEqual(self.db.query(PlanningAssignment).one().status, 'calendar_created')
        assign_show(self.req, self.db)
        calls = self.google.ensure_planned_event.call_args_list
        self.assertEqual(calls[0].args[1], calls[1].args[1])
        self.assertEqual(self.db.query(CalendarEvent).count(), 1)
        self.assertEqual(self.db.query(PlanningAssignment).one().status, 'complete')

    def test_changed_votes_during_google_write_stop_sheet_assignment(self):
        def calendar(*args): self.source['schedule'][2][1] = 'нет'
        self.google.ensure_planned_event.side_effect = calendar
        with self.assertRaises(HTTPException) as exc: assign_show(self.req, self.db)
        self.assertEqual(exc.exception.status_code, 409)
        self.client.api.values.return_value.batchUpdate.assert_not_called()
        self.assertEqual(self.db.query(PlanningAssignment).one().status, 'calendar_created')

    def test_invalid_actor_or_event_date_never_creates_event(self):
        for updates in ({'cast': {'Летте': 'Анна', 'Фанни': 'Анна'}}, {'start_time': datetime(2028, 10, 2, 19), 'end_time': datetime(2028, 10, 2, 21)}):
            with self.assertRaises(HTTPException): assign_show(self.req.model_copy(update=updates), self.db)
        self.google.ensure_planned_event.assert_not_called()


class GoogleIdempotencyTests(unittest.TestCase):
    def test_insert_conflict_reuses_event(self):
        client = GoogleCalendarClient.__new__(GoogleCalendarClient); client.service = MagicMock()
        body = {'summary': 'Урод', 'location': 'Зал', 'start': {'dateTime': '2028-10-01T19:00:00+03:00'}, 'end': {'dateTime': '2028-10-01T21:00:00+03:00'}}
        api = client.service.events.return_value
        api.get.return_value.execute.side_effect = [HttpError(Response({'status': '404'}), b'not found'), body]
        api.insert.return_value.execute.side_effect = HttpError(Response({'status': '409'}), b'conflict')
        self.assertEqual(client.ensure_planned_event('cal', 'fixed-id', body), body)
        self.assertEqual(api.insert.call_args.kwargs['body']['id'], 'fixed-id')

    def test_external_time_change_is_not_overwritten(self):
        client = GoogleCalendarClient.__new__(GoogleCalendarClient); client.service = MagicMock()
        body = {'summary': 'Урод', 'start': {'dateTime': '2028-10-01T19:00:00+03:00'}, 'end': {'dateTime': '2028-10-01T21:00:00+03:00'}}
        existing = copy.deepcopy(body); existing['start']['dateTime'] = '2028-10-01T20:00:00+03:00'
        client.service.events.return_value.get.return_value.execute.return_value = existing
        with self.assertRaises(ValueError): client.ensure_planned_event('cal', 'fixed-id', body)
        client.service.events.return_value.insert.assert_not_called()

class PlanningEdgeTests(unittest.TestCase):
    def test_duplicated_columns_cannot_schedule_two_events_for_one_date(self):
        source = fixture(); source['schedule'][0][2] = source['schedule'][0][1]
        plan = build_plan(source, '2028-10')
        self.assertEqual(plan['slots'][0]['shows'][0]['status'], 'ambiguous')
        with self.assertRaises(ValueError):
            assignment_updates(source, plan, 'B', 'Урод', {'Летте': 'Борис', 'Фанни': 'Анна'})

    def test_admin_dependency_is_enforced_after_telegram_auth(self):
        from fastapi import FastAPI, Depends
        from fastapi.testclient import TestClient
        from core.access import authorize_api, TelegramUser, _access_cache
        from modules.planning.router import router
        from unittest.mock import AsyncMock
        app = FastAPI(); app.include_router(router, dependencies=[Depends(authorize_api)])
        _access_cache.clear()
        with patch('core.access.verify_init_data', return_value=TelegramUser(42, 'actor')), patch('core.access._is_group_admin', AsyncMock(return_value=False)), patch('core.access.is_super_admin', AsyncMock(return_value=False)), patch('core.access._known_actor', return_value=True):
            client = TestClient(app)
            self.assertEqual(client.get('/api/planning').status_code, 403)
        _access_cache.clear()
