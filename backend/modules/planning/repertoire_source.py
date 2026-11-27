"""Read-only, daily projection of the shared ledger, role sheet and calendar."""
import copy
import json
from calendar import monthrange
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from threading import Lock
from time import monotonic

from core.time import as_local
from modules.attendance.models import DayAnswer
from modules.calendar.classification import classify_event
from modules.calendar.models import CalendarEvent
from modules.theater.routing import show_aliases, match_show
from sheets_client import _format_schedule_header

from .models import PlanningAssignment, RepertoireSettings
from .repertoire import Rules, default_rule, digest
from .services import build_plan, norm
from .show_times import show_format, PERFORMANCE_START_HOURS

_sheet_lock = Lock()
_sheet_cache = {}


def read_sheets(client, fresh=False):
    key = client.spreadsheet_id
    with _sheet_lock:
        cached = _sheet_cache.get(key)
        if not fresh and cached and monotonic() - cached[0] < 25:
            return copy.deepcopy(cached[1])
        value = client.get_planning_data()
        value['_actor_mapping'] = client.get_actor_mapping()
        _sheet_cache.clear()
        _sheet_cache[key] = (monotonic(), copy.deepcopy(value))
        return value


def load_snapshot(db, client, month, fresh=False):
    first = date.fromisoformat(month + '-01')
    last = first.replace(day=monthrange(first.year, first.month)[1])
    # Up to six days across each boundary for configurable seven-day runs.
    before, after = first - timedelta(days=6), last + timedelta(days=6)
    source = read_sheets(client, fresh)
    aliases = show_aliases(db)
    source['catalog'] = sorted({s.name for s in aliases.values()})
    source['show_aliases'] = {norm(k): s.name for k, s in aliases.items()}
    for row in source['casts'][1:]:
        show = match_show(row[0], aliases, exact=True) if row else None
        if show:
            row[0] = show.name
    source['availability'] = {}
    mapping = source.pop('_actor_mapping')
    answers = db.query(DayAnswer).filter(DayAnswer.day >= before, DayAnswer.day <= after).all()
    identities = defaultdict(set)
    for answer in answers:
        actor = answer.actor_name or mapping.get(answer.username)
        if isinstance(actor, str) and actor.strip():
            identities[norm(actor)].add(answer.user_id)
    # No Sheets export round trip. Ambiguous identities never imply availability.
    for answer in answers:
        actor = answer.actor_name or mapping.get(answer.username)
        if isinstance(actor, str) and actor.strip():
            key = norm(actor)
            source['availability'].setdefault(answer.day.isoformat(), {})[key] = answer.answer if len(identities[key]) == 1 else 'unknown'
    plan = build_plan(source, month)
    names = plan['shows']
    show_keys = {name: f'catalog:{aliases[norm(name)].id}' if norm(name) in aliases else 'sheet:' + norm(name) for name in names}
    warnings = list(plan['warnings'])
    original = defaultdict(list)
    for slot in plan['slots']:
        original[slot['date']].append(slot)
    daily = copy.deepcopy(source)
    rows = daily['schedule']
    if not rows:
        rows.extend([['Актёр'], ['']])
    elif len(rows) == 1:
        rows.append([''])
    width = max(len(row) for row in rows)
    for row in rows:
        row.extend([''] * (width - len(row)))
    for n in range(1, last.day + 1):
        day = first.replace(day=n)
        if day.isoformat() not in original:
            rows[0].append(_format_schedule_header(datetime.combine(day, time())))
            for row in rows[1:]:
                row.append('')
    daily_plan = build_plan(daily, month)
    fixed = {}
    occupied = defaultdict(list)
    rehearsals = defaultdict(list)
    calendar_events = defaultdict(list)
    # Existing assignments, including adjacent months, retain their actual cast.
    for selected_month in sorted({before.strftime('%Y-%m'), month, after.strftime('%Y-%m')}):
        for slot in build_plan(source, selected_month)['slots']:
            if not before.isoformat() <= slot['date'] <= after.isoformat() or not slot['assigned_show']:
                continue
            name = next((n for n in names if norm(n) == norm(slot['assigned_show'])), slot['assigned_show'])
            key = show_keys.get(name, 'sheet:' + norm(name))
            cell = next((c for c in slot['shows'] if c['show'] == name), None)
            # Only recorded roles identify a fixed cast; never infer it from availability.
            column_index = 0
            for char in slot['column']:
                column_index = column_index * 26 + ord(char) - ord('A') + 1
            cast = {}
            for role in (cell or {}).get('roles', []):
                assigned = [str(row[0]).strip() for row in source['schedule'][2:]
                            if len(row) >= column_index and norm(row[column_index - 1]) == norm(role['name'])
                            and norm(row[0]) in {norm(a['name']) for a in role['actors']}]
                if len(assigned) == 1:
                    cast[role['name']] = assigned[0]
            fixed[(slot['date'], key)] = {'date': slot['date'], 'key': key, 'name': name, 'cast': cast, 'fixed': True}
            occupied[slot['date']].append('В графике: ' + name)
            if not cell or len(cast) != cell['total']:
                warnings.append(f'{slot["date"]}, {name}: назначенный состав неполон или ответы изменились; нагрузка проверена только для известных исполнителей.')
    events = db.query(CalendarEvent).filter(
        CalendarEvent.start_time < as_local(datetime.combine(after + timedelta(days=1), time())),
        CalendarEvent.end_time > as_local(datetime.combine(before, time()))).order_by(CalendarEvent.id).all()
    operations = {op.id: op for op in db.query(PlanningAssignment).filter(PlanningAssignment.month.in_(
        sorted({before.strftime('%Y-%m'), month, after.strftime('%Y-%m')}))).all()}
    active_pairs = set()
    for event in events:
        if not event.is_cancelled and classify_event(event.title, aliases)['event_type'] == 'performance':
            show = match_show(event.title, aliases)
            name = show.name if show else classify_event(event.title, names)['show_name']
            active_pairs.add((as_local(event.start_time).date().isoformat(), show_keys.get(name)))
    event_signature = []
    for event in events:
        start, end = as_local(event.start_time), as_local(event.end_time)
        day = start.date().isoformat()
        event_signature.append([event.id, event.title, start.isoformat(), end.isoformat(), event.description, event.is_cancelled, event.is_all_day])
        op = operations.get(event.google_event_id)
        if op:
            request = json.loads(op.payload)['request']
            original_day = as_local(datetime.fromisoformat(request['start_time'])).date().isoformat()
            original_key = show_keys.get(request['show_name'])
            current_show = match_show(event.title, aliases)
            current_name = current_show.name if current_show else classify_event(event.title, names)['show_name']
            if event.is_cancelled or original_day != day or norm(current_name) != norm(request['show_name']):
                if fixed.pop((original_day, original_key), None):
                    warnings.append(f'{original_day}, {request["show_name"]}: календарное назначение изменено или отменено; старая запись графика не засчитана. Проверьте график.')
        if event.is_cancelled:
            show = match_show(event.title, aliases)
            name = show.name if show else classify_event(event.title, names)['show_name']
            key = show_keys.get(name)
            if classify_event(event.title, aliases)['event_type'] == 'performance' and (day, key) in fixed and (day, key) not in active_pairs:
                del fixed[(day, key)]
                warnings.append(f'{day}, {name}: показ отменён в календаре, но остался в графике. Он не засчитан в план; исправьте график перед новым назначением.')
            continue
        cursor = max(start.date(), before)
        end_day = (end - timedelta(microseconds=1)).date()
        event_type = classify_event(event.title, aliases)['event_type']
        while cursor <= min(end_day, after):
            # Rehearsal dates are interchangeable repertoire slots. Only the
            # event type matters here; the proposed show still needs its cast.
            if event_type == 'rehearsal':
                rehearsals[cursor.isoformat()].append({'event_id': event.id, 'title': event.title,
                    'start_time': start.isoformat(), 'end_time': end.isoformat()})
            elif event_type == 'performance':
                occupied[cursor.isoformat()].append('В календаре: ' + (event.title or 'Событие'))
            else:
                calendar_events[cursor.isoformat()].append({'event_id': event.id, 'title': event.title or 'Событие',
                    'start_time': start.isoformat(), 'end_time': end.isoformat(), 'all_day': bool(event.is_all_day)})
            cursor += timedelta(days=1)
        if event_type != 'performance':
            continue
        show = match_show(event.title, aliases)
        name = show.name if show else classify_event(event.title, names)['show_name']
        if not name:
            warnings.append(f'{day}: у показа «{event.title}» не определён спектакль и состав; он занимает дату, но не засчитывается в план.')
            continue
        key = show_keys.get(name, 'sheet:' + norm(name))
        item = fixed.setdefault((day, key), {'date': day, 'key': key, 'name': name, 'cast': {}, 'fixed': True})
        item.update(start_time=start.isoformat(), end_time=end.isoformat())
        if op:
            request = json.loads(op.payload)['request']
            if request['show_name'] == name and as_local(datetime.fromisoformat(request['start_time'])).date().isoformat() == day:
                item['cast'] = request['cast']
        if not item['cast']:
            warnings.append(f'{day}, {name}: состав календарного показа неизвестен; его нагрузка на актёров не проверена.')
    for op in operations.values():
        if op.status != 'complete':
            request = json.loads(op.payload)['request']
            day = as_local(datetime.fromisoformat(request['start_time'])).date().isoformat()
            occupied[day].append('Не завершено сохранение назначенного спектакля')
    slots, seen = [], set()
    for slot in daily_plan['slots']:
        day = slot['date']
        if day in seen:
            continue
        seen.add(day)
        slot['column'] = original[day][0]['column'] if len(original[day]) == 1 else None
        slot['blocked'] = '; '.join(sorted(set(occupied[day])))
        slot['calendar_events'] = calendar_events[day]
        if len(original[day]) > 1:
            slot['blocked'] = 'Несколько столбцов одной даты в графике: сначала объедините их'
        for cell in slot['shows']:
            cell['key'] = show_keys[cell['show']]
            cell['rehearsals'] = rehearsals[day]
        slots.append(slot)
    result = {'month': month, 'shows': [{'key': show_keys[n], 'name': n} for n in names],
              'slots': slots, 'fixed': sorted(fixed.values(), key=lambda s: (s['date'], s['key'])),
              'warnings': sorted(set(warnings)), 'source_fingerprint': plan['fingerprint']}
    # Prepared shares/publications must be reviewed again when show times change.
    result['fingerprint'] = digest([result, event_signature, [(op.id, op.status, op.payload) for op in operations.values()], PERFORMANCE_START_HOURS])
    return result


def get_rules(db, month, shows):
    row = db.get(RepertoireSettings, month)
    default = db.get(RepertoireSettings, '*')
    base = row or default
    rules = Rules.model_validate_json(base.payload) if base else Rules()
    if not row:
        rules.pins = []
    known = {s.key for s in rules.shows}
    rules.shows.extend(default_rule(s['key'], s['name']) for s in shows if s['key'] not in known)
    names = {s['key']: s['name'] for s in shows}
    for rule in rules.shows:
        if rule.format is None:
            rule.format = show_format(names.get(rule.key, ''))
    return rules, row.revision if row else 0, default.revision if default else 0
