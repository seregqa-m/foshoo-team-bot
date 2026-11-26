import copy
import os
import unittest
from datetime import date, datetime
from unittest.mock import MagicMock, patch

with patch.dict(os.environ, {'BOT_TOKEN': '123456:offline-test-token', 'DATABASE_URL': 'sqlite://', 'GOOGLE_CALENDAR_JSON': '/missing'}, clear=True), patch('dotenv.load_dotenv'):
    from core.database import Base
    from modules.planning.repertoire import Rules, ShowRule, Pin, RepertoireProblem, default_rule, load_warnings
    from modules.planning.repertoire_search import SearchJob
    from modules.planning.repertoire_source import load_snapshot, get_rules
    from modules.planning.repertoire_router import SaveRules, save_repertoire, valid_month, PrepareAssignment, prepare_assignment, validate_review
    from modules.planning.models import RepertoireSettings
    from modules.planning.router import router, AssignRequest
    from modules.attendance.models import DayAnswer
    from modules.calendar.models import CalendarEvent
    from modules.theater.models import TheaterShow
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def actor(name, status='yes'):
    return {'name': name, 'status': status, 'reason': {'yes': 'Свободен', 'no': 'Не может', 'unknown': 'Нет ответа'}[status]}


def fixture(days, names=('Урод',), casts=None):
    """days maps an ISO date to eligible show indices."""
    shows = [{'key': str(i), 'name': n} for i, n in enumerate(names)]
    slots = []
    for day, eligible in days.items():
        cells = []
        for i, name in enumerate(names):
            roles = (casts or {}).get(i, [{'name': 'Роль', 'actors': [actor('Актёр ' + str(i))]}])
            cells.append({'key': str(i), 'show': name, 'incomplete': False, 'status': 'ready' if i in eligible else 'waiting',
                          'roles': roles})
        slots.append({'date': day, 'shows': cells, 'blocked': ''})
    return {'month': '2028-10', 'fingerprint': 'test', 'shows': shows, 'slots': slots, 'fixed': []}


def variants(snapshot, rules):
    problem = RepertoireProblem(snapshot, rules, date(2028, 9, 1))
    return problem, [v for v in problem.search() if v is not None]


class RepertoireSolverTests(unittest.TestCase):
    def test_defaults_spread_for_every_show_and_weekends_for_long_shows(self):
        for name, count, days in [('Урод', 2, range(7)), ('Любовь Громова', 2, range(7)), ('Цианистый калий', 2, [5, 6]), ('Микрополь', 1, [5, 6]), ('Премьера', 0, range(7))]:
            rule = default_rule(name, name)
            self.assertEqual(rule.count, count)
            self.assertEqual(rule.weekdays, list(days))
            self.assertTrue(rule.spread)
            self.assertEqual(rule.gap, 14)

    def test_maximum_partial_and_each_different_shortfall_profile(self):
        data = fixture({'2028-10-01': [0, 1], '2028-10-02': [0, 1], '2028-10-03': [0, 1]}, ('Урод', 'Любовь Громова'))
        problem, results = variants(data, Rules(shows=[ShowRule(key='0', count=2), ShowRule(key='1', count=2)]))
        self.assertEqual(problem.upper, 3)
        self.assertEqual(len(results), 6)
        self.assertEqual({v['count'] for v in results}, {3})
        self.assertEqual({v['missing'][0]['key'] for v in results}, {'0', '1'})
        self.assertEqual(len({v['id'] for v in results}), 6)

    def test_one_missing_urod_keeps_all_other_targets(self):
        data = fixture({'2028-10-01': [0], '2028-10-02': [1], '2028-10-03': [1], '2028-10-04': [2], '2028-10-05': [2], '2028-10-06': [3]},
                       ('Урод', 'Любовь Громова', 'Цианистый калий', 'Микрополь'))
        _, results = variants(data, Rules(shows=[ShowRule(key=str(i), count=1 if i == 3 else 2) for i in range(4)]))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['count'], 6)
        self.assertEqual(results[0]['missing'], [{'key': '0', 'name': 'Урод', 'count': 1}])

    def test_close_dates_are_retained_and_rank_below_spread_dates(self):
        data = fixture({f'2028-10-{n:02}': [0] for n in (1, 8, 22)})
        problem, results = variants(data, Rules(shows=[ShowRule(key='0', count=2)]))
        self.assertEqual(len(results), 3)
        close = next(v for v in results if v['entries'][-1]['date'] == '2028-10-08')
        self.assertGreater(close['spread_score'], 0)
        self.assertTrue(any(v['spread_score'] == 0 for v in results))
        job = SearchJob(problem)
        try:
            while not job.complete:
                job.advance(1)
            page = job.page(size=1)
            self.assertEqual(page['total_variants'], 3)
            self.assertEqual(page['variants'][0]['spread_score'], 0)
            self.assertEqual(job.page(page=2, size=1)['variants'][0]['id'], close['id'])
        finally:
            job.close()

    def test_weekdays_premiere_and_occupied_dates_are_hard_constraints(self):
        data = fixture({f'2028-10-{n:02}': [0] for n in (1, 2, 7, 8, 14)})
        data['slots'][-1]['blocked'] = 'В календаре: аренда'
        problem, results = variants(data, Rules(shows=[ShowRule(key='0', count=3, weekdays=[5, 6], start=date(2028, 10, 5))]))
        self.assertEqual(results[0]['count'], 2)
        self.assertEqual({e['date'] for e in results[0]['entries']}, {'2028-10-07', '2028-10-08'})
        self.assertTrue(any('аренда' in (d['reason'] or '') for d in problem.diagnostics[0]['dates']))

    def test_alternative_actor_avoids_run_across_month_boundary(self):
        data = fixture({'2028-10-01': [0]}, casts={0: [{'name': 'Роль', 'actors': [actor('Анна'), actor('Борис')]}]})
        data['fixed'] = [{'date': day, 'key': 'other', 'name': 'Другой', 'cast': {'Роль': 'Анна'}, 'fixed': True} for day in ('2028-09-29', '2028-09-30')]
        _, results = variants(data, Rules(shows=[ShowRule(key='0', count=1)]))
        self.assertEqual(results[0]['entries'][0]['cast'], {'Роль': 'Борис'})
        self.assertEqual(results[0]['load_warnings'], [])

    def test_soft_load_warns_specific_actor_hard_load_finds_smaller_maximum(self):
        data = fixture({f'2028-10-0{n}': [0] for n in (1, 2, 3)})
        _, soft = variants(data, Rules(shows=[ShowRule(key='0', count=3)]))
        self.assertEqual(soft[0]['load_warnings'][0]['actor'], 'Актёр 0')
        self.assertEqual(soft[0]['count'], 3)
        _, hard = variants(data, Rules(shows=[ShowRule(key='0', count=3)], load_mode='forbid'))
        self.assertEqual(len(hard), 3)
        self.assertEqual({v['count'] for v in hard}, {2})

    def test_existing_counts_and_pins_are_not_moved(self):
        data = fixture({'2028-10-08': [0], '2028-10-22': [0]})
        data['fixed'] = [{'date': '2028-10-01', 'key': '0', 'name': 'Урод', 'cast': {'Роль': 'Актёр 0'}, 'fixed': True}]
        rules = Rules(shows=[ShowRule(key='0', count=2)], pins=[Pin(day='2028-10-22', key='0')])
        _, results = variants(data, rules)
        self.assertEqual(len(results), 1)
        self.assertEqual([s['date'] for s in results[0]['entries']], ['2028-10-01', '2028-10-22'])
        rules.pins = [Pin(day='2028-10-23', key='0')]
        problem, results = variants(data, rules)
        self.assertFalse(results)
        self.assertTrue(problem.pin_errors)

    def test_missing_answers_incomplete_cast_and_single_actor_for_two_roles(self):
        data = fixture({'2028-10-01': [], '2028-10-02': [0], '2028-10-03': [0]})
        data['slots'][1]['shows'][0]['incomplete'] = True
        data['slots'][2]['shows'][0]['roles'] = [{'name': role, 'actors': [actor('Анна')]} for role in ('А', 'Б')]
        _, results = variants(data, Rules(shows=[ShowRule(key='0', count=2)]))
        self.assertEqual(results[0]['count'], 0)

    def test_large_enumeration_is_resumable_not_truncated(self):
        data = fixture({f'2028-10-{n:02}': [0] for n in range(1, 12)})
        problem = RepertoireProblem(data, Rules(shows=[ShowRule(key='0', count=2)]), date(2028, 9, 1))
        job = SearchJob(problem)
        try:
            job.advance(0)
            self.assertFalse(job.page()['complete'])
            while not job.complete:
                job.advance(.01)
            self.assertEqual(job.page()['total_variants'], 55)
            self.assertEqual(len(job.page(page=2)['variants']), 15)
        finally:
            job.close()


class RepertoireSourceTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://')
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.db.add(TheaterShow(id=1, name='Урод', normalized_name='урод'))
        self.db.commit()
        self.client = MagicMock()
        self.client.spreadsheet_id = 'test'
        self.source = {'casts': [['Спектакль', 'Роль', 'Актёр'], ['Урод', 'Летте', 'Анна']],
                       'schedule': [['Актёр'], [''], ['Анна']]}
        self.client.get_planning_data.side_effect = lambda: copy.deepcopy(self.source)
        self.client.get_actor_mapping.return_value = {'anna': 'Анна'}

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def answer(self, day, value, user=1):
        row = self.db.get(DayAnswer, (user, date.fromisoformat(day)))
        if row:
            row.answer = value
        else:
            self.db.add(DayAnswer(user_id=user, day=date.fromisoformat(day), actor_name='Анна', username='anna', answer=value, source='test'))
        self.db.commit()

    def test_full_month_without_sheet_columns_and_immediate_shared_answer(self):
        self.answer('2028-10-07', 'yes')
        data = load_snapshot(self.db, self.client, '2028-10', fresh=True)
        self.assertEqual(len(data['slots']), 31)
        cell = data['slots'][6]['shows'][0]
        self.assertEqual(cell['status'], 'ready')
        self.assertIsNone(data['slots'][6]['column'])
        self.answer('2028-10-07', 'no')
        newer = load_snapshot(self.db, self.client, '2028-10')
        self.assertEqual(newer['slots'][6]['shows'][0]['status'], 'blocked')
        self.assertNotEqual(data['fingerprint'], newer['fingerprint'])
        self.client.api.values.return_value.batchUpdate.assert_not_called()

    def test_calendar_counts_existing_and_excludes_cancelled_and_occupied(self):
        self.db.add_all([
            CalendarEvent(title='Урод [Спект]', google_event_id='a', start_time=datetime(2028, 10, 7, 19), end_time=datetime(2028, 10, 7, 21)),
            CalendarEvent(title='Урод [Спект]', google_event_id='b', start_time=datetime(2028, 10, 8, 19), end_time=datetime(2028, 10, 8, 21), is_cancelled=True),
            CalendarEvent(title='Аренда', google_event_id='c', start_time=datetime(2028, 10, 9, 10), end_time=datetime(2028, 10, 9, 12)),
        ])
        self.db.commit()
        data = load_snapshot(self.db, self.client, '2028-10', fresh=True)
        self.assertEqual(len(data['fixed']), 1)
        self.assertTrue(data['slots'][6]['blocked'])
        self.assertFalse(data['slots'][7]['blocked'])
        self.assertIn('Аренда', data['slots'][8]['blocked'])
        self.assertTrue(data['warnings'])

    def test_duplicate_actor_identity_never_grants_ready_cast(self):
        self.answer('2028-10-07', 'yes')
        self.answer('2028-10-07', 'yes', user=2)
        data = load_snapshot(self.db, self.client, '2028-10', fresh=True)
        self.assertNotEqual(data['slots'][6]['shows'][0]['status'], 'ready')

    def test_cancelled_calendar_show_does_not_count_stale_sheet_assignment(self):
        self.source['schedule'] = [['Актёр', '7 окт 2028'], ['', 'Урод'], ['Анна', 'Летте']]
        self.db.add(CalendarEvent(title='Урод [Спект]', google_event_id='cancelled', start_time=datetime(2028, 10, 7, 19), end_time=datetime(2028, 10, 7, 21), is_cancelled=True))
        self.db.commit()
        data = load_snapshot(self.db, self.client, '2028-10', fresh=True)
        self.assertFalse(data['fixed'])
        self.assertTrue(any('отменён' in w for w in data['warnings']))

    def test_prepare_stale_snapshot_does_not_write_and_valid_prepare_returns_review(self):
        self.answer('2028-10-07', 'yes')
        original = load_snapshot(self.db, self.client, '2028-10', fresh=True)
        req = PrepareAssignment(month='2028-10', day='2028-10-07', key='catalog:1', expected_fingerprint='stale', expected_revision=0)
        with patch('modules.planning.router.get_client', return_value=self.client), patch('modules.planning.repertoire_router.local_now', return_value=datetime(2028, 9, 1)):
            with self.assertRaises(HTTPException) as ctx:
                prepare_assignment(req, self.db)
            self.assertEqual(ctx.exception.status_code, 409)
            self.client.ensure_schedule_columns.assert_not_called()
            req.expected_fingerprint = original['fingerprint']
            def add_column(*args):
                self.source['schedule'] = [['Актёр', '7 окт 2028'], ['', ''], ['Анна', '']]
            self.client.ensure_schedule_columns.side_effect = add_column
            with patch('modules.planning.router.get_planning', return_value={'slots': [{'date': '2028-10-07', 'column': 'B'}]}):
                result = prepare_assignment(req, self.db)
            self.assertEqual(result['column'], 'B')
            self.assertEqual(result['repertoire']['key'], 'catalog:1')
            self.assertNotEqual(result['repertoire']['fingerprint'], original['fingerprint'])

    def test_new_calendar_conflict_invalidates_final_assignment_review(self):
        self.answer('2028-10-07', 'yes')
        snapshot = load_snapshot(self.db, self.client, '2028-10', fresh=True)
        req = AssignRequest(month='2028-10', column='B', show_name='Урод', cast={'Летте': 'Анна'},
            expected_fingerprint='sheet', start_time='2028-10-07T19:00', end_time='2028-10-07T21:00', location='Зал',
            repertoire={'key': 'catalog:1', 'fingerprint': snapshot['fingerprint'], 'revision': 0})
        with patch('modules.planning.repertoire_router.local_now', return_value=datetime(2028, 9, 1)):
            validate_review(self.db, self.client, req, date(2028, 10, 7))
            self.db.add(CalendarEvent(title='Аренда', google_event_id='new', start_time=datetime(2028, 10, 7, 18), end_time=datetime(2028, 10, 7, 22)))
            self.db.commit()
            with self.assertRaises(HTTPException) as ctx:
                validate_review(self.db, self.client, req, date(2028, 10, 7))
            self.assertEqual(ctx.exception.status_code, 409)

    def test_month_rules_defaults_revision_conflicts_and_horizon(self):
        shows = [{'key': 'catalog:1', 'name': 'Урод'}]
        rules, revision, defaults_revision = get_rules(self.db, '2031-01', shows)
        self.assertEqual(revision, 0)
        rules.shows[0].count = 3
        req = SaveRules(month='2031-01', rules=rules, expected_revision=0, expected_defaults_revision=0, use_as_default=True)
        save_repertoire(req, self.db)
        with self.assertRaises(HTTPException) as ctx:
            save_repertoire(req, self.db)
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(get_rules(self.db, '2031-02', shows)[0].shows[0].count, 3)
        self.assertEqual(get_rules(self.db, '2031-01', shows)[1], 1)
        self.assertEqual(valid_month('2035-12'), '2035-12')
        for month in ('2028-13', '2028-1', '0001-01'):
            with self.assertRaises(HTTPException):
                valid_month(month)

    def test_default_changes_do_not_overwrite_configured_month(self):
        shows = [{'key': 'catalog:1', 'name': 'Урод'}]
        rules, _, _ = get_rules(self.db, '2028-10', shows)
        save_repertoire(SaveRules(month='2028-10', rules=rules, expected_revision=0, expected_defaults_revision=0), self.db)
        rules.shows[0].count = 4
        save_repertoire(SaveRules(month='2028-11', rules=rules, expected_revision=0, expected_defaults_revision=0, use_as_default=True), self.db)
        self.assertEqual(get_rules(self.db, '2028-10', shows)[0].shows[0].count, 2)

    def test_every_repertoire_route_has_local_admin_guard(self):
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)
        self.assertEqual(client.get('/api/planning/repertoire?month=2028-10').status_code, 403)
        self.assertEqual(client.put('/api/planning/repertoire', json={}).status_code, 403)
        self.assertEqual(client.post('/api/planning/repertoire/prepare', json={}).status_code, 403)
