"""A small, quality-ranked set of meaningfully different schedules."""
from collections import defaultdict
from datetime import date


def profile(variant):
    return tuple(sorted((s['key'], s['count']) for s in variant['missing']))


def pairs(variant):
    return {(e['date'], e['key']) for e in variant['entries']}


def different(a, b):
    if profile(a) != profile(b):
        return True
    removed, added = pairs(a) - pairs(b), pairs(b) - pairs(a)
    if min(len(removed), len(added)) >= 2:
        return True
    if len(removed) == len(added) == 1:
        old, new = next(iter(removed)), next(iter(added))
        return old[1] == new[1] and abs((date.fromisoformat(old[0]) - date.fromisoformat(new[0])).days) >= 7
    return False


def shortlist(ranked, limit=5):
    """ranked is a repeatable iterator factory, ordered by load/spread/id.

    Keep distinct shortfalls and diverse schedules of comparable quality first.
    Fill remaining places with nearby moves, then schedules with soft tradeoffs.
    Soft preferences rank alternatives; they never hide all remaining choices.
    """
    leaders = {}
    selected = []
    for variant in ranked():
        key = profile(variant)
        if key not in leaders:
            leaders[key] = variant
            selected.append(variant)
            if len(selected) == limit:
                return selected
    for comparable, diverse in ((True, True), (True, False), (False, True), (False, False)):
        if len(selected) >= limit:
            break
        for variant in ranked():
            leader = leaders[profile(variant)]
            if comparable and (variant['load_score'] > leader['load_score'] or variant['spread_score'] > leader['spread_score'] + 7):
                continue
            if any(pairs(variant) == pairs(other) for other in selected):
                continue
            if diverse and not all(different(variant, other) for other in selected):
                continue
            selected.append(variant)
            if len(selected) == limit:
                break
    return sorted(selected, key=lambda v: (v['load_score'], v['spread_score'], v['id']))


def changes(reference, variant):
    before, after, names = defaultdict(set), defaultdict(set), {}
    for e in reference['entries']:
        before[e['key']].add(e['date']); names[e['key']] = e['name']
    for e in variant['entries']:
        after[e['key']].add(e['date']); names[e['key']] = e['name']
    return [{'key': key, 'name': names[key], 'from': sorted(before[key] - after[key]), 'to': sorted(after[key] - before[key])}
            for key in sorted(names, key=lambda k: (names[k], k)) if before[key] != after[key]]
