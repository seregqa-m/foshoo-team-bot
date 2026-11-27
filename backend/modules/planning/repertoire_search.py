"""Cooperative exhaustive search cache, disk-backed so variants don't fill RAM.

Single-process deployment. LRU jobs can be rebuilt from their immutable input;
no source data is written. Request work is time-sliced; the UI gets a shortlist.
"""
import json
import sqlite3
import tempfile
from collections import OrderedDict, Counter
from threading import RLock
from time import monotonic

from .repertoire import digest
from .repertoire_recommendations import shortlist, changes


class SearchJob:
    def __init__(self, problem):
        self.problem = problem
        self.generator = problem.search()
        self.directory = tempfile.TemporaryDirectory(prefix='foshoo-repertoire-')
        self.db = sqlite3.connect(self.directory.name + '/variants.sqlite', check_same_thread=False)
        self.db.execute('CREATE TABLE variants (id TEXT PRIMARY KEY, load INTEGER, spread INTEGER, payload TEXT, summary TEXT)')
        self.db.execute('CREATE INDEX rank ON variants(load, spread, id)')
        self.complete = False
        self.best_count = None
        self.steps = 0

    def advance(self, seconds=.20):
        deadline = monotonic() + seconds
        while not self.complete and monotonic() < deadline:
            try:
                variant = next(self.generator)
            except StopIteration:
                self.complete = True
                break
            self.steps += 1
            if variant is not None:
                self.best_count = variant['count']
                summary = {k: variant[k] for k in ('id', 'load_score', 'spread_score', 'missing')}
                summary['entries'] = [{k: e[k] for k in ('date', 'key', 'name')} for e in variant['entries']]
                self.db.execute('INSERT OR IGNORE INTO variants VALUES (?, ?, ?, ?, ?)',
                    (variant['id'], variant['load_score'], variant['spread_score'], json.dumps(variant, ensure_ascii=False), json.dumps(summary, ensure_ascii=False)))
        self.db.commit()

    def page(self, page=0, size=20, selected=None):
        count = self.db.execute('SELECT count(*) FROM variants').fetchone()[0]
        page = min(page, max(0, (count - 1) // size))
        rows = self.db.execute('SELECT payload FROM variants ORDER BY load, spread, id LIMIT ? OFFSET ?', (size, page * size)).fetchall()
        chosen = self.db.execute('SELECT payload FROM variants WHERE id=?', (selected,)).fetchone() if selected else None
        return {'variants': [json.loads(r[0]) for r in rows], 'selected_variant': json.loads(chosen[0]) if chosen else None,
                'total_variants': count, 'page': page, 'page_size': size, 'complete': self.complete,
                'maximum': self.best_count, 'upper_bound': self.problem.upper, 'target': self.problem.target,
                'search_steps': self.steps, 'pin_errors': self.problem.pin_errors}

    def close(self):
        self.generator.close()
        self.db.close()
        self.directory.cleanup()

    def recommendations(self, selected=None):
        def ranked():
            for row in self.db.execute('SELECT summary FROM variants ORDER BY load, spread, id'):
                yield json.loads(row[0])
        picked = shortlist(ranked)
        retained = None
        if selected and picked and all(v['id'] != selected for v in picked):
            row = self.db.execute('SELECT summary FROM variants WHERE id=?', (selected,)).fetchone()
            if row:
                retained = selected
                # Keep the current calendar stable as the search improves;
                # retain it inside the limit, never as a sixth alternative.
                picked = picked[:4] + [json.loads(row[0])]
        variants = []
        reference = picked[0] if picked else None
        for item in picked:
            variant = json.loads(self.db.execute('SELECT payload FROM variants WHERE id=?', (item['id'],)).fetchone()[0])
            variant['changes'] = changes(reference, item)
            variant['retained'] = variant['id'] == retained
            variants.append(variant)
        return {'variants': variants, 'selected_variant': next((v for v in variants if v['id'] == selected), None),
                'recommended_id': reference['id'] if reference else None,
                'total_variants': len(variants), 'considered_variants': self.db.execute('SELECT count(*) FROM variants').fetchone()[0],
                'page': 0, 'page_size': 5, 'complete': self.complete, 'maximum': self.best_count,
                'upper_bound': self.problem.upper, 'target': self.problem.target,
                'search_steps': self.steps, 'pin_errors': self.problem.pin_errors}


_jobs = OrderedDict()
_drafts = OrderedDict()
_lock = RLock()


def search_page(problem, page=0, selected=None):
    key = search_key(problem)
    with _lock:
        job = _jobs.get(key)
        if job is None:
            job = _jobs[key] = SearchJob(problem)
        _jobs.move_to_end(key)
        while len(_jobs) > 4:
            _jobs.popitem(last=False)[1].close()
        job.advance()
        return {'search_id': key, **job.recommendations(selected=selected)}


def search_key(problem):
    return digest([problem.snapshot['fingerprint'], problem.rules.model_dump(mode='json'), problem.today])


def cached_variant(search_id, variant_id):
    with _lock:
        draft = _drafts.get((search_id, variant_id))
        if draft and draft['variant']:
            return draft['variant']
        job = _jobs.get(search_id)
        if job is None:
            return None
        row = job.db.execute('SELECT payload FROM variants WHERE id=?', (variant_id,)).fetchone()
        return json.loads(row[0]) if row else None


def draft_variant(problem, selected):
    """Validate one explicit schedule cooperatively, outside the automatic list."""
    pairs = [(e['date'], e['key']) for e in problem.current_fixed] + [(day, key) for day, key, _ in selected]
    key = (search_key(problem), digest(['manual', sorted(pairs)]))
    with _lock:
        if key not in _drafts:
            _drafts[key] = {'generator': problem._best_cast(selected), 'variant': None, 'complete': False}
        _drafts.move_to_end(key)
        while len(_drafts) > 32:
            _drafts.popitem(last=False)[1]['generator'].close()
        draft = _drafts[key]
        deadline = monotonic() + .20
        while not draft['complete'] and monotonic() < deadline:
            try:
                value = next(draft['generator'])
            except StopIteration:
                draft['complete'] = True
                break
            if value is not None:
                value['id'] = key[1]
                counts = Counter(e['key'] for e in value['entries'])
                value['manual'] = True
                value['excess'] = [{'key': r.key, 'name': problem.names.get(r.key, r.key), 'count': counts[r.key] - r.count}
                                   for r in problem.rules.shows if counts[r.key] > r.count]
                draft['variant'], draft['complete'] = value, True
                draft['generator'].close()
        return {'status': 'ready' if draft['variant'] else 'invalid' if draft['complete'] else 'calculating',
                'variant': draft['variant'], 'search_id': key[0]}
