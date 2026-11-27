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

from .services import norm, match_roles
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


class DraftEntry(Pin):
    start_time: str | None = Field(default=None, pattern=r'^([01][0-9]|2[0-3]):[0-5][0-9]$')


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


def projected_casts(roles, relevant):
    """One feasible cast per relevant actor set, without role permutations.

    Match required actors to roles first, then augment to cover the remaining
    roles. Augmentation preserves each required actor's participation.
    """
    available = [{norm(a['name']): a['name'] for a in role['actors']
                  if a['status'] in ('yes', 'assigned')} for role in roles]
    def match(required, excluded):
        choices = [[a for a in actors if a not in excluded] for actors in available]
        owners = {}
        def place_actor(actor, seen):
            for i, actors in enumerate(choices):
                if actor not in actors or i in seen:
                    continue
                seen.add(i)
                if i not in owners or place_actor(owners[i], seen):
                    owners[i] = actor
                    return True
            return False
        if any(not place_actor(a, set()) for a in required):
            return None
        assigned = {a: i for i, a in owners.items()}
        def place_role(i, seen):
            for actor in choices[i]:
                if actor in seen:
                    continue
                seen.add(actor)
                if actor not in assigned or place_role(assigned[actor], seen):
                    assigned[actor] = i
                    return True
            return False
        for i in range(len(roles)):
            if i not in owners and not place_role(i, set()):
                return None
        return {roles[i]['name']: available[i][actor]
                for actor, i in assigned.items()}

    actors = sorted(relevant)
    def visit(index, required, excluded):
        yield None
        cast = match(required, excluded)
        if cast is None:
            return
        if index == len(actors):
            yield cast
            return
        yield from visit(index + 1, required, excluded | {actors[index]})
        yield from visit(index + 1, required + [actors[index]], excluded)
    yield from visit(0, [], set())


class RepertoireProblem:
    def __init__(self, snapshot, rules, today, start_times=None):
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
        self._mandatory = {}
        for slot in snapshot['slots']:
            day = date.fromisoformat(slot['date'])
            candidates = {}
            for cell in slot['shows']:
                key = cell['key']
                if key not in self.rule or not self.remaining[key]:
                    continue
                r = self.rule[key]
                time_error = None
                try:
                    window = performance_window(day, self.names[key], r.format, (start_times or {}).get((slot['date'], key)))
                except ValueError as exc:
                    window, time_error = None, str(exc)
                conflicts = calendar_conflicts(slot.get('calendar_events', []), *window) if window else []
                reason = None
                if day < today:
                    reason = 'Дата уже прошла'
                elif day.weekday() not in r.weekdays:
                    reason = 'День недели запрещён параметрами'
                elif time_error:
                    reason = time_error
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
        available_by_day = defaultdict(set)
        for entry in self.fixed:
            available_by_day[entry['date']].update(norm(a) for a in entry.get('cast', {}).values())
        for day, _, cell in selected:
            available_by_day[day].update(norm(a['name']) for r in cell['roles'] for a in r['actors'] if a['status'] in ('yes', 'assigned'))
        critical = defaultdict(set)
        days = sorted(available_by_day)
        if self.rules.load_mode != 'ignore':
            for i in range(len(days) - self.rules.streak + 1):
                window = days[i:i + self.rules.streak]
                if (date.fromisoformat(window[-1]) - date.fromisoformat(window[0])).days == self.rules.streak - 1:
                    actors = set.intersection(*(available_by_day[d] for d in window))
                    for day in window:
                        critical[day].update(actors)
        mandatory = []
        for day, key, cell in selected:
            cache_key = (day, key)
            if not critical[day]:
                mandatory.append({'date': day, 'cast': {}})
                continue
            if cache_key not in self._mandatory:
                required = []
                available = {norm(a['name']): a['name'] for r in cell['roles'] for a in r['actors'] if a['status'] in ('yes', 'assigned')}
                for actor_key, name in available.items():
                    yield None
                    without = [{**r, 'actors': [a for a in r['actors'] if norm(a['name']) != actor_key]} for r in cell['roles']]
                    if len(match_roles(without)) < len(cell['roles']):
                        required.append(name)
                self._mandatory[cache_key] = {str(i): name for i, name in enumerate(required)}
            mandatory.append({'date': day, 'cast': self._mandatory[cache_key]})
        baseline = {(norm(w['actor']), tuple(w['dates'])) for w in load_warnings(self.fixed, self.rules.streak)}

        def assess(entries):
            warnings = load_warnings(self.fixed + entries, self.rules.streak)
            added = [w for w in warnings if (norm(w['actor']), tuple(w['dates'])) not in baseline]
            score = sum(len(w['dates']) - self.rules.streak + 1 for w in added) if self.rules.load_mode != 'ignore' else 0
            return score, warnings

        # Every complete cast contains these actors, so their load is a proven
        # lower bound. Stop once attained, even if some load is unavoidable.
        minimum, _ = assess(mandatory)
        def visit(index, entries):
            nonlocal best
            yield None
            lower, _ = assess(entries + mandatory[index:])
            if (self.rules.load_mode == 'forbid' and lower) or (best is not None and lower >= best[0]):
                return
            if index == len(selected):
                score, warnings = assess(entries)
                if best is None or score < best[0]:
                    best = (score, entries.copy(), warnings)
                return
            day, key, cell = selected[index]
            # Forced actors cannot vary between casts; branching on their
            # inclusion only produces infeasible exclusions.
            forced = {norm(a) for a in mandatory[index]['cast'].values()}
            for cast in projected_casts(cell['roles'], critical[day] - forced):
                yield None
                if cast is not None:
                    yield from visit(index + 1, entries + [{'date': day, 'key': key, 'name': self.names[key], 'cast': cast,
                                                          'fixed': False, 'rehearsals': cell.get('rehearsals', []),
                                                          'start_time': cell['start_time'], 'end_time': cell['end_time']}])
                    if best is not None and best[0] == minimum:
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
        fixed_days = {date.fromisoformat(e['date']).toordinal() for e in self.fixed}
        base_days = fixed_days | {date.fromisoformat(day).toordinal() for day, _, _ in self.pinned}
        ordinals = {day: date.fromisoformat(day).toordinal() for day in days}

        def has_run(selected_days):
            return any(all(day + offset in selected_days for offset in range(1, self.rules.streak))
                       for day in selected_days)

        # Start with schedules that cannot create actor streaks at all. Their
        # casts need no cross-day optimization. The complementary pass still
        # examines every other schedule, including consecutive shows with
        # different actors. Partition by dates rather than storing seen IDs.
        separated_first = self.rules.load_mode != 'ignore' and not has_run(base_days)

        def visit(index, needed, capacities, chosen, selected_days, separated):
            yield None
            if needed == 0:
                if not separated_first or has_run(selected_days) != separated:
                    yield from self._best_cast(self.pinned + chosen)
                return
            if index == len(days) or len(days) - index < needed or sum(min(n, suffix[index][key]) for key, n in capacities.items()) < needed:
                return
            day = days[index]
            next_days = selected_days | {ordinals[day]}
            if not separated or not has_run(next_days):
                for key in self.options[day]:
                    if capacities[key] > 0:
                        capacities[key] -= 1
                        yield from visit(index + 1, needed - 1, capacities, chosen + [(day, key, self.options[day][key])], next_days, separated)
                        capacities[key] += 1
            yield from visit(index + 1, needed, capacities, chosen, selected_days, separated)
        for size in range(self.upper - self.counted_fixed - len(self.pinned), -1, -1):
            found = False
            for separated in ([True, False] if separated_first else [False]):
                for result in visit(0, size, self.remaining.copy(), [], base_days, separated):
                    if result is not None:
                        found = True
                    yield result
            if found:
                return
