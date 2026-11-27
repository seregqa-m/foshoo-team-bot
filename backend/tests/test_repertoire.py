import copy
import os
import random
import unittest
from itertools import combinations, product
from datetime import date, datetime
from unittest.mock import MagicMock, patch

with patch.dict(os.environ, {'BOT_TOKEN': '123456:offline-test-token', 'DATABASE_URL': 'sqlite://', 'GOOGLE_CALENDAR_JSON': '/missing'}, clear=True), patch('dotenv.load_dotenv'):
    from core.database import Base
    from modules.planning.repertoire import Rules, ShowRule, Pin, RepertoireProblem, default_rule, load_warnings, casts, projected_casts
    from modules.planning.repertoire_search import SearchJob
    from modules.planning.repertoire_source import load_snapshot, get_rules
    from modules.planning.repertoire_router import SaveRules, save_repertoire, valid_month, PrepareAssignment, prepare_assignment, validate_review
    from modules.planning.models import RepertoireSettings
    from modules.planning.show_times import performance_window
    from modules.planning.router import router, AssignRequest
    from modules.attendance.models import DayAnswer
    from modules.calendar.models import CalendarEvent
    from modules.theater.models import TheaterShow, TheaterShowAlias
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
    def test_january_starts_with_unloaded_schedules_and_keeps_all_275(self):
        ready = [{16, 17, 18, 23, 25, 30, 31}, {23, 24, 30},
                 {16, 17, 23, 24, 25, 30, 31}, {16, 17, 22, 23, 24, 30}]
        data = fixture({f'2027-01-{d:02}': [i for i, dates in enumerate(ready) if d in dates]
                        for d in sorted(set.union(*ready))},
                       ('Любовь Громова', 'Микрополь', 'Урод', 'Цианистый Калий'),
                       casts={i: [{'name': 'Роль', 'actors': [actor('Общий актёр')]}] for i in range(4)})
        data['month'] = '2027-01'
        rules = Rules(shows=[ShowRule(key=str(i), count=n) for i, n in enumerate((2, 2, 1, 2))])
        problem = RepertoireProblem(data, rules, date(2026, 11, 27))
        results = []
        first_five_steps = None
        for steps, result in enumerate(problem.search()):
            if result is not None:
                results.append(result)
                if len(results) == 5:
                    first_five_steps = steps
        self.assertEqual(len(results), 275)
        self.assertEqual(len({v['id'] for v in results}), 275)
        self.assertLess(first_five_steps, 1000)
        self.assertTrue(all(v['count'] == 7 and v['load_score'] == 0 for v in results[:5]))
        self.assertTrue(any(v['load_score'] > 0 for v in results))

    def test_search_partition_preserves_every_schedule_with_pins_and_existing_runs(self):
        days = [f'2028-10-{n:02}' for n in range(1, 6)]
        for mode, threshold, existing_run in product(('prefer', 'forbid', 'ignore'), (2, 3), (False, True)):
            data = fixture({day: [0, 1] for day in days}, ('Урод', 'Любовь Громова'),
                           casts={i: [{'name': 'Роль', 'actors': [actor('Анна'), actor('Борис')]}] for i in range(2)})
            if existing_run:
                data['fixed'] = [{'date': day, 'key': 'old', 'name': 'Старый', 'cast': {'Роль': 'Анна'}, 'fixed': True}
                                 for day in ('2028-09-28', '2028-09-29', '2028-09-30')]
            rules = Rules(shows=[ShowRule(key='0', count=2), ShowRule(key='1', count=1)],
                          pins=[Pin(day=days[0], key='0')], load_mode=mode, streak=threshold)
            problem = RepertoireProblem(data, rules, date(2028, 9, 1))
            expected = {}
            for extra_days in combinations(days[1:], 2):
                for keys in (('0', '1'), ('1', '0')):
                    selected = problem.pinned + [(d, k, problem.options[d][k]) for d, k in zip(extra_days, keys)]
                    for v in problem._best_cast(selected):
                        if v is not None:
                            expected[v['id']] = v['load_score']
            results = [v for v in problem.search() if v is not None]
            self.assertEqual({v['id']: v['load_score'] for v in results}, expected, (mode, threshold, existing_run))
            self.assertEqual(len(results), len(expected))

    def test_projected_casts_preserve_every_feasible_relevant_actor_set(self):
        rng = random.Random(30)
        names = ['А', 'Б', 'В', 'Г', 'Д']
        for iteration in range(80):
            roles = [{'name': f'Роль {i}', 'actors': [actor(n) for n in rng.sample(names, rng.randint(1, 5))]} for i in range(3)]
            relevant = {n.casefold() for n in rng.sample(names, rng.randint(0, 5))}
            key = lambda cast: frozenset(a.casefold() for a in cast.values()) & relevant
            expected = {key(cast) for cast in casts(roles) if cast is not None}
            actual = [cast for cast in projected_casts(roles, relevant) if cast is not None]
            self.assertEqual({key(cast) for cast in actual}, expected, f'case {iteration}')
            self.assertEqual(len(actual), len(expected))
            for cast in actual:
                self.assertEqual(len(set(cast.values())), len(roles))
                self.assertTrue(all(any(a['name'] == cast[r['name']] for a in r['actors']) for r in roles))

    def test_mandatory_actor_bound_avoids_factorial_role_permutations(self):
        roles = [{'name': f'Роль {i}', 'actors': [actor(f'Актёр {j}') for j in range(8)]} for i in range(8)]
        data = fixture({'2028-10-01': [0], '2028-10-02': [0], '2028-10-03': [0]}, casts={0: roles})
        problem = RepertoireProblem(data, Rules(shows=[ShowRule(key='0', count=3)]), date(2028, 9, 1))
        selected = [(day, '0', cells['0']) for day, cells in problem.options.items()]
        results = []
        for steps, result in enumerate(problem._best_cast(selected)):
            self.assertLess(steps, 1000, 'Must not enumerate permutations after reaching a proven minimum')
            if result is not None:
                results.append(result)
        self.assertEqual(results[0]['load_score'], 8)
        self.assertEqual(len(results[0]['load_warnings']), 8)

    def test_cast_pruning_matches_exhaustive_minimum_including_existing_runs(self):
        rng = random.Random(27)
        for iteration in range(45):
            data = fixture({'2028-10-01': [0], '2028-10-02': [0], '2028-10-03': [0]})
            for slot in data['slots']:
                slot['shows'][0]['roles'] = [{'name': f'Роль {i}', 'actors': [actor(n) for n in rng.sample(['А', 'Б', 'В', 'Г'], rng.randint(2, 4))]} for i in range(2)]
            if iteration % 2:
                data['fixed'] = [{'date': day, 'key': 'old', 'name': 'Другой', 'cast': {'Роль': 'А'}, 'fixed': True}
                                 for day in ('2028-09-28', '2028-09-29', '2028-09-30')]
            mode = ['prefer', 'forbid', 'ignore'][iteration % 3]
            rules = Rules(shows=[ShowRule(key='0', count=3)], load_mode=mode)
            problem = RepertoireProblem(data, rules, date(2028, 9, 1))
            selected = [(day, '0', cells['0']) for day, cells in problem.options.items()]
            choices = [[c for c in casts(cell['roles']) if c is not None] for _, _, cell in selected]
            baseline = {(w['actor'], tuple(w['dates'])) for w in load_warnings(data['fixed'], 3)}
            expected = None
            for combination in product(*choices):
                entries = [{'date': item[0], 'cast': cast} for item, cast in zip(selected, combination)]
                added = [w for w in load_warnings(data['fixed'] + entries, 3) if (w['actor'], tuple(w['dates'])) not in baseline]
                if mode == 'forbid' and added:
                    continue
                score = 0 if mode == 'ignore' else sum(len(w['dates']) - 2 for w in added)
                expected = score if expected is None else min(expected, score)
            actual = [v for v in problem._best_cast(selected) if v is not None]
            self.assertEqual(actual[0]['load_score'] if actual else None, expected, f'case {iteration}: {mode}')

    def test_start_times_for_every_weekday_and_both_formats(self):
        for day, small, large in [(2, '20:00', None), (3, '20:00', None), (4, '20:00', None), (5, '20:00', None),
                                   (6, '19:00', '19:00'), (7, '19:00', '18:00'), (8, '19:00', '18:00')]:
            for name, expected in [('Урод', small), ('Цианистый Калий', large)]:
                window = performance_window(date(2028, 10, day), name)
                if expected is None:
                    self.assertIsNone(window)
                else:
                    self.assertEqual(window[0].strftime('%H:%M'), expected)
                    self.assertEqual((window[1] - window[0]).total_seconds(), 5400 if name == 'Урод' else 10800)

    def test_january_30_afternoon_lab_allows_second_kaliy_with_soft_13_day_gap(self):
        data = fixture({'2027-01-17': [0], '2027-01-30': [0]}, names=('Цианистый Калий',))
        data['month'] = '2027-01'
        data['slots'][1]['calendar_events'] = [{'title': 'Лаба Игошиной', 'start_time': '2027-01-30T12:00:00+03:00', 'end_time': '2027-01-30T16:00:00+03:00'}]
        rules = Rules(shows=[ShowRule(key='0', count=2, weekdays=[4, 5, 6])])
        problem = RepertoireProblem(data, rules, date(2026, 11, 27))
        results = [v for v in problem.search() if v is not None]
        self.assertEqual(results[0]['count'], 2)
        self.assertEqual(results[0]['entries'][1]['start_time'], '2027-01-30T18:00:00+03:00')
        self.assertEqual(results[0]['entries'][1]['end_time'], '2027-01-30T21:00:00+03:00')
        self.assertEqual(results[0]['spread_warnings'][0]['gap'], 13)

    def test_overlap_depends_on_show_window_and_exact_boundaries(self):
        data = fixture({'2028-10-07': [0, 1]}, names=('Урод', 'Цианистый Калий'))
        rules = Rules(shows=[ShowRule(key='0', count=1), ShowRule(key='1', count=1)])
        event = {'title': 'Лаба', 'start_time': '2028-10-07T15:30:00Z', 'end_time': '2028-10-07T16:00:00Z'}
        data['slots'][0]['calendar_events'] = [event]  # 18:30–19:00 Moscow
        problem, _ = variants(data, rules)
        self.assertEqual(set(problem.options['2028-10-07']), {'0'})
        self.assertIn('Лаба (18:30–19:00)', problem.diagnostics[1]['dates'][0]['reason'])
        event.update(start_time='2028-10-07T21:00:00+03:00', end_time='2028-10-08T01:00:00+03:00')
        self.assertEqual(set(variants(data, rules)[0].options['2028-10-07']), {'0', '1'})
        event['start_time'] = '2028-10-07T20:59:00+03:00'
        self.assertEqual(set(variants(data, rules)[0].options['2028-10-07']), {'0'})
        event.update(start_time='2028-10-06T23:00:00+03:00', end_time='2028-10-08T01:00:00+03:00')
        self.assertNotIn('2028-10-07', variants(data, rules)[0].options)

    def test_large_show_cannot_use_monday_even_if_saved_weekdays_allow_it(self):
        data = fixture({'2028-10-02': [0]}, names=('Цианистый Калий',))
        problem, results = variants(data, Rules(shows=[ShowRule(key='0', count=1)]))
        self.assertEqual(results[0]['count'], 0)
        self.assertIn('Большие спектакли', problem.diagnostics[0]['dates'][0]['reason'])
        # An explicit format for a new production controls the same time policy.
        data['shows'][0]['name'] = 'Новая премьера'
        problem, _ = variants(data, Rules(shows=[ShowRule(key='0', count=1, format='large')]))
        self.assertNotIn('2028-10-02', problem.options)

    def test_defaults_spread_for_every_show_and_friday_weekends_for_large_shows(self):
        for name, count, days in [('Урод', 2, range(7)), ('Любовь Громова', 2, range(7)), ('Цианистый калий', 2, [4, 5, 6]), ('Микрополь', 1, [4, 5, 6]), ('Премьера', 0, range(7))]:
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
        data = fixture({'2028-10-01': [0], '2028-10-02': [1], '2028-10-03': [1], '2028-10-06': [2], '2028-10-07': [2], '2028-10-08': [3]},
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
        self.assertFalse(data['slots'][8]['blocked'])
        self.assertEqual(data['slots'][8]['calendar_events'][0]['title'], 'Аренда')
        self.assertTrue(data['warnings'])

    def test_duplicate_actor_identity_never_grants_ready_cast(self):
        self.answer('2028-10-07', 'yes')
        self.answer('2028-10-07', 'yes', user=2)
        data = load_snapshot(self.db, self.client, '2028-10', fresh=True)
        self.assertNotEqual(data['slots'][6]['shows'][0]['status'], 'ready')

    def test_rehearsal_is_a_slot_for_any_complete_cast_not_a_fixed_performance(self):
        self.db.add(TheaterShow(id=2, name='Другой', normalized_name='другой'))
        self.source['casts'].append(['Другой', 'Роль', 'Анна'])
        self.answer('2028-10-07', 'yes')
        self.db.add(CalendarEvent(title='Урод [Реп]', google_event_id='rehearsal', start_time=datetime(2028, 10, 7, 19), end_time=datetime(2028, 10, 7, 21)))
        self.db.commit()
        data = load_snapshot(self.db, self.client, '2028-10', fresh=True)
        self.assertFalse(data['fixed'])
        rules = Rules(shows=[ShowRule(key='catalog:1', count=1), ShowRule(key='catalog:2', count=1)])
        problem, results = variants(data, rules)
        self.assertEqual(set(problem.options['2028-10-07']), {'catalog:1', 'catalog:2'})
        self.assertEqual(len(results), 2)
        self.assertEqual({v['count'] for v in results}, {1})
        self.assertEqual({v['entries'][0]['key'] for v in results}, {'catalog:1', 'catalog:2'})
        self.assertTrue(all(v['entries'][0]['rehearsals'][0]['title'] == 'Урод [Реп]' for v in results))
        other = next(d for d in problem.diagnostics if d['key'] == 'catalog:2')
        self.assertIsNone(next(d for d in other['dates'] if d['date'] == '2028-10-07')['reason'])

    def test_matching_rehearsal_never_waives_other_events_or_missing_answers(self):
        self.db.add(TheaterShow(id=2, name='Другой', normalized_name='другой'))
        self.db.commit()
        for extra in ('Аренда', 'Уборка', 'Неизвестное событие', 'Урод [Спект]'):
            with self.subTest(event=extra):
                self.db.query(CalendarEvent).delete()
                self.answer('2028-10-07', 'yes')
                self.db.add_all([CalendarEvent(title=title, google_event_id=str(i), start_time=datetime(2028, 10, 7, 19), end_time=datetime(2028, 10, 7, 21)) for i, title in enumerate(['Урод [Реп]', extra])])
                self.db.commit()
                data = load_snapshot(self.db, self.client, '2028-10', fresh=True)
                problem = RepertoireProblem(data, Rules(shows=[ShowRule(key='catalog:1', count=2)]), date(2028, 9, 1))
                self.assertNotIn('catalog:1', problem.options.get('2028-10-07', {}))
        self.db.query(CalendarEvent).delete()
        self.db.add(CalendarEvent(title='Урод [Реп]', google_event_id='r', start_time=datetime(2028, 10, 7, 19), end_time=datetime(2028, 10, 7, 21)))
        self.answer('2028-10-07', 'unknown')
        data = load_snapshot(self.db, self.client, '2028-10', fresh=True)
        problem = RepertoireProblem(data, Rules(shows=[ShowRule(key='catalog:1', count=1)]), date(2028, 9, 1))
        self.assertNotIn('2028-10-07', problem.options)

    def test_rehearsal_alias_bracketed_name_cancellation_and_exclusive_midnight(self):
        self.db.add(TheaterShowAlias(normalized_name='старое имя', show_id=1))
        self.answer('2028-10-07', 'yes')
        self.answer('2028-10-08', 'yes')
        for title in ('Репетиция [Урод]', 'СТАРОЕ ИМЯ [реп]', 'Другой [Реп]', '[Реп]', 'Урод и Другой [Реп]'):
            with self.subTest(title=title):
                self.db.query(CalendarEvent).delete()
                self.db.add(CalendarEvent(title=title, google_event_id='r', start_time=datetime(2028, 10, 7, 19), end_time=datetime(2028, 10, 8)))
                self.db.commit()
                data = load_snapshot(self.db, self.client, '2028-10', fresh=True)
                self.assertEqual(len(data['slots'][6]['shows'][0]['rehearsals']), 1)
                problem = RepertoireProblem(data, Rules(shows=[ShowRule(key='catalog:1', count=1)]), date(2028, 9, 1))
                self.assertIn('catalog:1', problem.options['2028-10-07'])
                self.assertFalse(data['slots'][7]['shows'][0]['rehearsals'])
                self.db.query(CalendarEvent).one().is_cancelled = True
                self.db.commit()
                data = load_snapshot(self.db, self.client, '2028-10', fresh=True)
                self.assertFalse(data['slots'][6]['shows'][0]['rehearsals'])
                self.assertFalse(data['slots'][6]['blocked'])

    def test_rehearsal_slot_passes_final_review_and_changed_show_invalidates_it(self):
        self.answer('2028-10-07', 'yes')
        self.db.add(CalendarEvent(title='Урод [Реп]', google_event_id='r', start_time=datetime(2028, 10, 7, 19), end_time=datetime(2028, 10, 7, 21)))
        self.db.commit()
        data = load_snapshot(self.db, self.client, '2028-10', fresh=True)
        req = AssignRequest(month='2028-10', column='B', show_name='Урод', cast={'Летте': 'Анна'},
            expected_fingerprint='sheet', start_time='2028-10-07T19:00', end_time='2028-10-07T20:30', location='Зал',
            repertoire={'key': 'catalog:1', 'fingerprint': data['fingerprint'], 'revision': 0})
        with patch('modules.planning.repertoire_router.local_now', return_value=datetime(2028, 9, 1)):
            validate_review(self.db, self.client, req, date(2028, 10, 7))
            self.db.query(CalendarEvent).one().title = 'Репетиция другого спектакля'
            self.db.commit()
            with self.assertRaises(HTTPException) as ctx:
                validate_review(self.db, self.client, req, date(2028, 10, 7))
            self.assertEqual(ctx.exception.status_code, 409)
            req.repertoire.fingerprint = load_snapshot(self.db, self.client, '2028-10', fresh=True)['fingerprint']
            validate_review(self.db, self.client, req, date(2028, 10, 7))

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
            self.assertEqual(result['repertoire']['start_time'], '2028-10-07T19:00:00+03:00')
            self.assertEqual(result['repertoire']['end_time'], '2028-10-07T20:30:00+03:00')
            self.assertNotEqual(result['repertoire']['fingerprint'], original['fingerprint'])

    def test_new_calendar_conflict_invalidates_final_assignment_review(self):
        self.answer('2028-10-07', 'yes')
        snapshot = load_snapshot(self.db, self.client, '2028-10', fresh=True)
        req = AssignRequest(month='2028-10', column='B', show_name='Урод', cast={'Летте': 'Анна'},
            expected_fingerprint='sheet', start_time='2028-10-07T19:00', end_time='2028-10-07T20:30', location='Зал',
            repertoire={'key': 'catalog:1', 'fingerprint': snapshot['fingerprint'], 'revision': 0})
        with patch('modules.planning.repertoire_router.local_now', return_value=datetime(2028, 9, 1)):
            validate_review(self.db, self.client, req, date(2028, 10, 7))
            self.db.add(CalendarEvent(title='Аренда', google_event_id='new', start_time=datetime(2028, 10, 7, 18), end_time=datetime(2028, 10, 7, 22)))
            self.db.commit()
            with self.assertRaises(HTTPException) as ctx:
                validate_review(self.db, self.client, req, date(2028, 10, 7))
            self.assertEqual(ctx.exception.status_code, 409)

    def test_final_review_rejects_a_time_different_from_the_proposal(self):
        self.answer('2028-10-07', 'yes')
        snapshot = load_snapshot(self.db, self.client, '2028-10', fresh=True)
        req = AssignRequest(month='2028-10', column='B', show_name='Урод', cast={'Летте': 'Анна'},
            expected_fingerprint='sheet', start_time='2028-10-07T18:00', end_time='2028-10-07T19:30', location='Зал',
            repertoire={'key': 'catalog:1', 'fingerprint': snapshot['fingerprint'], 'revision': 0})
        with patch('modules.planning.repertoire_router.local_now', return_value=datetime(2028, 9, 1)):
            with self.assertRaises(HTTPException) as ctx:
                validate_review(self.db, self.client, req, date(2028, 10, 7))
            self.assertEqual(ctx.exception.status_code, 409)
            self.assertIn('Время отличается', ctx.exception.detail)

    def test_all_day_and_cancelled_events_respect_window(self):
        self.answer('2028-10-07', 'yes')
        self.db.add(CalendarEvent(title='Аренда', google_event_id='day', is_all_day=True,
            start_time=datetime(2028, 10, 7), end_time=datetime(2028, 10, 8)))
        self.db.commit()
        rules = Rules(shows=[ShowRule(key='catalog:1', count=1)])
        data = load_snapshot(self.db, self.client, '2028-10', fresh=True)
        problem, _ = variants(data, rules)
        self.assertNotIn('2028-10-07', problem.options)
        reason = next(d['reason'] for d in problem.diagnostics[0]['dates'] if d['date'] == '2028-10-07')
        self.assertIn('весь день', reason)
        self.db.query(CalendarEvent).one().is_cancelled = True
        self.db.commit()
        data = load_snapshot(self.db, self.client, '2028-10', fresh=True)
        self.assertIn('2028-10-07', variants(data, rules)[0].options)

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
