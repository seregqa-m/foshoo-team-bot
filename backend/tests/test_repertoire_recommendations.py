import copy
import unittest
from types import SimpleNamespace

import test_repertoire  # Isolated test configuration before importing the planner.
from modules.planning.repertoire_search import SearchJob
from modules.planning.repertoire_recommendations import shortlist, different, changes


def variant(id, days=(1, 15), load=0, spread=0, missing=()):
    return {'id': id, 'load_score': load, 'spread_score': spread, 'count': 2,
            'missing': [{'key': k, 'name': k, 'count': 1} for k in missing],
            'entries': [{'date': f'2028-10-{day:02}', 'key': key, 'name': name, 'cast': {'Роль': 'Анна'}, 'fixed': False}
                        for day, key, name in zip(days, ('a', 'b'), ('Урод', 'Калий'))]}


def pick(values):
    ordered = sorted(values, key=lambda v: (v['load_score'], v['spread_score'], v['id']))
    return shortlist(lambda: iter(ordered))


class RepertoireRecommendationTests(unittest.TestCase):
    def test_eighty_schedules_become_at_most_five_distinct_recommendations(self):
        values = [variant(f'{a:02}-{b:02}', (a, b)) for a in range(1, 9) for b in range(15, 25)]
        result = pick(values)
        self.assertEqual(len(result), 5)
        self.assertEqual(result[0]['id'], values[0]['id'])
        self.assertTrue(all(different(a, b) for i, a in enumerate(result) for b in result[i + 1:]))

    def test_nearby_moves_fill_free_places_after_diverse_choices(self):
        values = [variant(f'{day:02}', (1, day)) for day in range(15, 21)]
        self.assertEqual(len(pick(values)), 5)
        values.append(variant('week', (1, 22)))
        self.assertEqual(len(pick(values)), 5)
        self.assertIn('week', {v['id'] for v in pick(values)})
        self.assertEqual(len(pick(values[:2])), 2)

    def test_soft_tradeoffs_remain_available_after_better_alternatives(self):
        best = variant('a')
        load = variant('b', (8, 23), load=1)
        spread = variant('c', (9, 24), spread=8)
        allowed = variant('d', (10, 25), spread=7)
        self.assertEqual([v['id'] for v in pick([spread, load, allowed, best])], ['a', 'd', 'c', 'b'])

    def test_nearby_unloaded_schedules_take_priority_over_loaded_diverse_ones(self):
        values = [variant(str(i), (1, 15 + i)) for i in range(5)]
        values.append(variant('loaded', (8, 25), load=1))
        result = pick(values)
        self.assertEqual(len(result), 5)
        self.assertTrue(all(v['load_score'] == 0 for v in result))

    def test_same_dates_and_shows_never_fill_places_with_other_casts(self):
        best = variant('a')
        duplicate = copy.deepcopy(best)
        duplicate['id'] = 'b'
        duplicate['entries'][0]['cast'] = {'Роль': 'Борис'}
        self.assertEqual([v['id'] for v in pick([best, duplicate])], ['a'])

    def test_different_shortfalls_keep_their_best_representatives(self):
        values = [variant('best-a', missing=('a',)), variant('near-a', (1, 16), missing=('a',)),
                  variant('best-b', load=1, missing=('b',)), variant('best-c', spread=20, missing=('c',))]
        self.assertEqual({v['id'] for v in pick(values)}, {'best-a', 'near-a', 'best-b', 'best-c'})

    def test_more_than_five_shortfalls_still_respect_the_limit(self):
        self.assertEqual(len(pick([variant(str(i), missing=(str(i),)) for i in range(9)])), 5)

    def test_differences_describe_changed_dates_not_actor_permutations(self):
        reference = variant('a')
        same = copy.deepcopy(reference); same['entries'][0]['cast']['Роль'] = 'Борис'
        self.assertEqual(changes(reference, same), [])
        self.assertFalse(different(reference, same))
        self.assertEqual(changes(reference, variant('b', (1, 22))), [{'key': 'b', 'name': 'Калий', 'from': ['2028-10-15'], 'to': ['2028-10-22']}])
        swapped = variant('c'); swapped['entries'][1].update(key='c', name='Микрополь')
        result = changes(reference, swapped)
        self.assertEqual(next(c for c in result if c['key'] == 'b')['to'], [])
        self.assertEqual(next(c for c in result if c['key'] == 'c')['from'], [])

    def test_selected_calendar_stays_inside_five_without_replacing_recommended(self):
        values = [variant('00-best'), variant('01-near', (1, 16))] + [variant(f'v{i}', (i, i + 15)) for i in range(2, 9)]
        job = SearchJob(SimpleNamespace(search=lambda: (v for v in values), upper=2, target=2, pin_errors=[]))
        try:
            job.advance(1)
            result = job.recommendations(selected='01-near')
            self.assertLessEqual(result['total_variants'], 5)
            self.assertEqual(result['considered_variants'], len(values))
            self.assertEqual(result['recommended_id'], '00-best')
            self.assertEqual(result['variants'][0]['id'], '00-best')
            self.assertEqual(result['selected_variant']['id'], '01-near')
            self.assertTrue(result['selected_variant']['retained'])
            self.assertTrue(result['selected_variant']['changes'])
            self.assertIsNone(job.recommendations('deleted')['selected_variant'])
        finally:
            job.close()
