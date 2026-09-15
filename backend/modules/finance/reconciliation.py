"""Stable row matching and serialization for the single-worker finance cache."""
import hashlib
import json
from collections import defaultdict, deque
from functools import wraps
from threading import RLock

_lock = RLock()


def serialized_finance(fn):
    @wraps(fn)
    def call(*args, **kwargs):
        with _lock:
            return fn(*args, **kwargs)
    return call


def row_values(row):
    fields = ('project', 'date', 'amount', 'what', 'comment')
    if hasattr(row, 'expense_type'):
        fields += ('who', 'expense_type')
    return {key: getattr(row, key) or (0 if key == 'amount' else '') for key in fields}


def fingerprint(row):
    return hashlib.sha256(json.dumps(row_values(row), ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def reconcile(db, model, incoming):
    """Match a multiset of complete rows, preserving IDs of unchanged entries."""
    existing = defaultdict(deque)
    for row in db.query(model).all():
        existing[fingerprint(row)].append(row)
    for values in incoming:
        candidate = model(**values)
        matches = existing[fingerprint(candidate)]
        if matches:
            matches.popleft()
        else:
            db.add(candidate)
    db.flush()  # Allocate new IDs before deleting old rows.
    for remaining in existing.values():
        for row in remaining:
            db.delete(row)
