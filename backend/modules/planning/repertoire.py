"""Pure monthly repertoire search. Every yield is a cooperative work checkpoint.

Enumerate all maximum-cardinality date/show schedules; interchangeable casts do
not multiply the schedule list. For each schedule find the least loaded cast.
No heuristic cutoffs: callers time-slice the generator, never truncate it.
"""
import hashlib
import json
from collections import Counter, defaultdict
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from .services import norm
from .show_times import performance_window, show_format, calendar_conflicts, conflict_reason


class ShowRule(BaseModel):
    key: str = Field(min_length=1, max_length=250)
    count: int = Field(default=0, ge=0, le=31, strict=True)
    weekdays: list[int] = Field(default_factory=lambda: list(range(7)), min_length=1, max_length=7)
    spread: bool = True
    gap: int = Field(default=14, ge=1, le=31, strict=True)
    start: date | None = None
    format: Literal['small', 'large'] | None = None

    @model_validator(mode='after')
    def valid_days(self):
        if any(type(d) is not int or d not in range(7) for d in self.weekdays) or len(set(self.weekdays)) != len(self.weekdays):
            raise ValueError('Выберите неповторяющиеся дни недели от 0 до 6')
        return self


class Pin(BaseModel):
    day: date
    key: str


class Rules(BaseModel):
    shows: list[ShowRule] = Field(default_factory=list, max_length=100)
    streak: int = Field(default=3, ge=2, le=7, strict=True)
    load_mode: Literal['prefer', 'forbid', 'ignore'] = 'prefer'
    pins: list[Pin] = Field(default_factory=list, max_length=31)

    @model_validator(mode='after')
    def unique(self):
        if len({s.key for s in self.shows}) != len(self.shows):
            raise ValueError('Спектакль указан несколько раз')
        if len({p.day for p in self.pins}) != len(self.pins):
            raise ValueError('На дату можно закрепить только один спектакль')
        return self


def default_rule(key, name):
    name = norm(name)
    return ShowRule(key=key, count={'урод': 2, 'любовь громова': 2, 'цианистый калий': 2, 'микрополь': 1}.get(name, 0),
                    weekdays=[4, 5, 6] if show_format(name) == 'large' else list(range(7)), format=show_format(name))


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def load_warnings(entries, threshold):
    actors = defaultdict(dict)
    for entry in entries:
        for actor in entry.get('cast', {}).values():
            actors[norm(actor)][entry['date']] = actor
    result = []
    for days in actors.values():
        run = []
        for day in sorted(days):
            if run and (date.fromisoformat(day) - date.fromisoformat(run[-1])).days != 1:
                if len(run) >= threshold:
                    result.append({'actor': days[run[0]], 'dates': run})
                run = []
            run.append(day)
        if len(run) >= threshold:
            result.append({'actor': days[run[0]], 'dates': run})
    return result


def casts(roles):
    """Yield complete injective assignments, and None while exploring."""
    roles = sorted(roles, key=lambda r: len(r['actors']))
    def visit(index, chosen, used):
        yield None
        if index == len(roles):
            yield chosen.copy()
            return
        role = roles[index]
        for actor in role['actors']:
            key = norm(actor['name'])
            if actor['status'] not in ('yes', 'assigned') or key in used:
                continue
            chosen[role['name']] = actor['name']
            yield from visit(index + 1, chosen, used | {key})
            del chosen[role['name']]
    yield from visit(0, {}, set())


def maximum_count(options, capacities):
    """Exact b-matching upper bound: show copies ↔ distinct free days."""
    owners = {}
    def place(copy, seen):
        for day, keys in options.items():
            if copy[0] not in keys or day in seen:
                continue
            seen.add(day)
            if day not in owners or place(owners[day], seen):
                owners[day] = copy
                return True
        return False
    for key, count in capacities.items():
        for i in range(count):
            place((key, i), set())
    return len(owners)


class RepertoireProblem:
    def __init__(self, snapshot, rules, today):
        self.snapshot, self.rules = snapshot, rules
        self.today = today
        self.names = {s['key']: s['name'] for s in snapshot['shows']}
        self.rule = {s.key: s for s in rules.shows}
        self.fixed = snapshot['fixed']
        self.current_fixed = [s for s in self.fixed if s['date'].startswith(snapshot['month'])]
        self.fixed_counts = Counter(s['key'] for s in self.current_fixed)
        self.counted_fixed = sum(min(r.count, self.fixed_counts[r.key]) for r in rules.shows)
        self.target = sum(r.count for r in rules.shows)
        self.remaining = {r.key: max(0, r.count - self.fixed_counts[r.key]) for r in rules.shows}
        self.diagnostics = {key: {'key': key, 'name': self.names.get(key, key), 'ready_dates': [], 'dates': []} for key in self.rule}
        self.options = {}
        for slot in snapshot['slots']:
            day = date.fromisoformat(slot['date'])
            candidates = {}
            for cell in slot['shows']:
                key = cell['key']
                if key not in self.rule or not self.remaining[key]:
                    continue
                r = self.rule[key]
                window = performance_window(day, self.names[key], r.format)
                conflicts = calendar_conflicts(slot.get('calendar_events', []), *window) if window else []
                reason = None
                if day < today:
                    reason = 'Дата уже прошла'
                elif day.weekday() not in r.weekdays:
                    reason = 'День недели запрещён параметрами'
                elif window is None:
                    reason = 'Большие спектакли разрешены только в пятницу, субботу и воскресенье'
                elif r.start and day < r.start:
                    reason = 'Раньше даты готовности спектакля'
                elif slot.get('blocked'):
                    reason = slot['blocked']
                elif conflicts:
                    reason = conflict_reason(conflicts)
                elif cell['incomplete']:
                    reason = 'Не заполнены роли или исполнители спектакля'
                elif cell['status'] != 'ready':
                    reason = 'Нужны ответы исполнителей' if cell['status'] == 'waiting' else 'Не хватает разных доступных исполнителей для всех ролей'
                diagnostic = {'date': slot['date'], 'reason': reason, 'roles': cell['roles'],
                              'rehearsals': cell.get('rehearsals', []),
                              'start_time': window[0].isoformat() if window else None,
                              'end_time': window[1].isoformat() if window else None}
                self.diagnostics[key]['dates'].append(diagnostic)
                if reason is None:
                    candidates[key] = {**cell, 'start_time': window[0].isoformat(), 'end_time': window[1].isoformat()}
                    self.diagnostics[key]['ready_dates'].append(slot['date'])
            if candidates:
                self.options[slot['date']] = candidates
        self.pin_errors = []
        self.pinned = []
        fixed_pairs = {(s['date'], s['key']) for s in self.current_fixed}
        for pin in rules.pins:
            day = pin.day.isoformat()
            if (day, pin.key) in fixed_pairs:
                continue
            if pin.key not in self.options.get(day, {}) or self.remaining.get(pin.key, 0) <= 0:
                self.pin_errors.append(f'{day}: закреплённый {self.names.get(pin.key, pin.key)} больше не подходит. Проверьте ответы и параметры или снимите закрепление.')
                continue
            self.pinned.append((day, pin.key, self.options[day][pin.key]))
            self.remaining[pin.key] -= 1
            del self.options[day]
        self.upper = self.counted_fixed + len(self.pinned) + maximum_count(self.options, self.remaining)
        self.diagnostics = list(self.diagnostics.values())

    def _best_cast(self, selected):
        best = None
        def visit(index, entries):
            nonlocal best
            yield None
            if best is not None and best[0] == 0:
                return
            if index == len(selected):
                warnings = load_warnings(self.fixed + entries, self.rules.streak)
                # Existing violations are visible but cannot make every new plan impossible.
                baseline = {(w['actor'], tuple(w['dates'])) for w in load_warnings(self.fixed, self.rules.streak)}
                added = [w for w in warnings if (w['actor'], tuple(w['dates'])) not in baseline]
                if self.rules.load_mode == 'forbid' and added:
                    return
                score = sum(len(w['dates']) - self.rules.streak + 1 for w in added) if self.rules.load_mode != 'ignore' else 0
                if best is None or score < best[0]:
                    best = (score, entries.copy(), warnings)
                return
            day, key, cell = selected[index]
            for cast in casts(cell['roles']):
                yield None
                if cast is not None:
                    yield from visit(index + 1, entries + [{'date': day, 'key': key, 'name': self.names[key], 'cast': cast,
                                                          'fixed': False, 'rehearsals': cell.get('rehearsals', []),
                                                          'start_time': cell['start_time'], 'end_time': cell['end_time']}])
                    if best is not None and best[0] == 0:
                        break
        yield from visit(0, [])
        if best is not None:
            load, entries, warnings = best
            entries = sorted(self.current_fixed + entries, key=lambda s: (s['date'], s['key']))
            gaps, spread_score = [], 0
            for key, rule in self.rule.items():
                if not rule.spread:
                    continue
                dates = sorted({s['date'] for s in entries if s['key'] == key})
                for a, b in zip(dates, dates[1:]):
                    interval = (date.fromisoformat(b) - date.fromisoformat(a)).days
                    same_part = min((int(a[-2:]) - 1) // 10, 2) == min((int(b[-2:]) - 1) // 10, 2)
                    penalty = max(0, rule.gap - interval) + int(same_part)
                    spread_score += penalty
                    if penalty:
                        gaps.append({'name': self.names[key], 'dates': [a, b], 'gap': interval, 'desired': rule.gap, 'same_part': same_part})
            counts = Counter(s['key'] for s in entries)
            missing = [{'key': r.key, 'name': self.names.get(r.key, r.key), 'count': r.count - counts[r.key]} for r in self.rules.shows if counts[r.key] < r.count]
            yield {'id': digest([(s['date'], s['key']) for s in entries]), 'entries': entries,
                   'load_score': load, 'spread_score': spread_score, 'load_warnings': warnings,
                   'spread_warnings': gaps, 'missing': missing,
                   'count': sum(min(r.count, counts[r.key]) for r in self.rules.shows)}

    def search(self):
        if self.pin_errors:
            return
        # Visit spaced dates first to produce useful recommendations immediately;
        # this changes traversal only, not completeness or the final ranking.
        chronological = sorted(self.options)
        gap = next((r.gap for r in self.rules.shows if r.spread and r.count > 1), 14)
        days = []
        for day in chronological:
            if day not in days:
                days.append(day)
                later = date.fromordinal(date.fromisoformat(day).toordinal() + gap).isoformat()
                if later in self.options and later not in days:
                    days.append(later)
        suffix = [Counter() for _ in range(len(days) + 1)]
        for i in range(len(days) - 1, -1, -1):
            suffix[i] = suffix[i + 1] + Counter(self.options[days[i]].keys())
        def visit(index, needed, capacities, chosen):
            yield None
            if needed == 0:
                yield from self._best_cast(self.pinned + chosen)
                return
            if index == len(days) or len(days) - index < needed or sum(min(n, suffix[index][key]) for key, n in capacities.items()) < needed:
                return
            day = days[index]
            for key in self.options[day]:
                if capacities[key] > 0:
                    capacities[key] -= 1
                    yield from visit(index + 1, needed - 1, capacities, chosen + [(day, key, self.options[day][key])])
                    capacities[key] += 1
            yield from visit(index + 1, needed, capacities, chosen)
        for size in range(self.upper - self.counted_fixed - len(self.pinned), -1, -1):
            found = False
            for result in visit(0, size, self.remaining.copy(), []):
                if result is not None:
                    found = True
                yield result
            if found:
                return
