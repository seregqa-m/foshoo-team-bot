"""Cooperative exhaustive search cache, disk-backed so variants don't fill RAM.

Single-process deployment. LRU jobs can be rebuilt from their immutable input;
no source data is written. Request work is time-sliced, results are paginated.
"""
import json
import sqlite3
import tempfile
from collections import OrderedDict
from threading import RLock
from time import monotonic

from .repertoire import digest


class SearchJob:
    def __init__(self, problem):
        self.problem = problem
        self.generator = problem.search()
        self.directory = tempfile.TemporaryDirectory(prefix='foshoo-repertoire-')
        self.db = sqlite3.connect(self.directory.name + '/variants.sqlite', check_same_thread=False)
        self.db.execute('CREATE TABLE variants (id TEXT PRIMARY KEY, load INTEGER, spread INTEGER, payload TEXT)')
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
                self.db.execute('INSERT OR IGNORE INTO variants VALUES (?, ?, ?, ?)',
                    (variant['id'], variant['load_score'], variant['spread_score'], json.dumps(variant, ensure_ascii=False)))
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


_jobs = OrderedDict()
_lock = RLock()


def search_page(problem, page=0, selected=None):
    key = digest([problem.snapshot['fingerprint'], problem.rules.model_dump(mode='json'), problem.today])
    with _lock:
        job = _jobs.get(key)
        if job is None:
            job = _jobs[key] = SearchJob(problem)
        _jobs.move_to_end(key)
        while len(_jobs) > 4:
            _jobs.popitem(last=False)[1].close()
        job.advance()
        return {'search_id': key, **job.page(page, selected=selected)}
