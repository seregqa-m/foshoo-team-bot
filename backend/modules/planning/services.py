"""Cast planning from the current schedule and role roster, without external writes."""
import hashlib
import json
import re
from collections import defaultdict
from datetime import date

from sheets_client import _parse_header_date, _col_num_to_letter


def norm(value):
    return ' '.join(str(value).split()).casefold()


def match_roles(roles, allowed_statuses=('yes', 'assigned')):
    """Maximum bipartite matching: a distinct available actor for every role."""
    actor_to_role = {}
    def place(role_index, seen):
        for actor in roles[role_index]['actors']:
            key = norm(actor['name'])
            if actor['status'] not in allowed_statuses or key in seen:
                continue
            seen.add(key)
            if key not in actor_to_role or place(actor_to_role[key], seen):
                actor_to_role[key] = role_index
                return True
        return False
    for index in range(len(roles)):
        place(index, set())
    return {
        roles[index]['name']: next(a['name'] for a in roles[index]['actors'] if norm(a['name']) == actor)
        for actor, index in actor_to_role.items()
    }


def build_plan(source, month):
    first = date.fromisoformat(month + '-01')
    shows = {}
    warnings = []
    for row in source['casts'][1:]:
        name = str(row[0]).strip() if row else ''
        if not name:
            continue
        show = shows.setdefault(norm(name), {'name': name, 'roles': {}, 'incomplete': False})
        role = str(row[1]).strip() if len(row) > 1 else ''
        actor = str(row[2]).strip() if len(row) > 2 else ''
        if not role or not actor:
            show['incomplete'] = True
            continue
        entry = show['roles'].setdefault(norm(role), {'name': role, 'actors': {}})
        entry['actors'][norm(actor)] = actor
    rows = source['schedule']
    headers = rows[0] if rows else []
    names = rows[1] if len(rows) > 1 else []
    actor_rows = defaultdict(list)
    for index, row in enumerate(rows[2:], 3):
        if row and str(row[0]).strip():
            actor_rows[norm(row[0])].append((index, row))
    slots = []
    for index, header in enumerate(headers[1:], 1):
        parsed = _parse_header_date(str(header), first.year)
        if not parsed or parsed.year != first.year or parsed.month != first.month:
            continue
        slots.append({'column': _col_num_to_letter(index + 1), 'index': index,
                      'date': parsed.date().isoformat(), 'time': parsed.strftime('%H:%M'), 'label': str(header),
                      'assigned_show': str(names[index]).strip() if len(names) > index else ''})
        if not re.search(r'\b\d{4}\b', str(header)):
            warnings.append('В старых заголовках графика нет года: они показаны в выбранном году. Проверьте даты перед назначением.')
    slots.sort(key=lambda s: (s['date'], s['time'], s['index']))
    for slot in slots:
        slot['duplicate'] = sum(s['date'] == slot['date'] and s['time'] == slot['time'] for s in slots) > 1
    if any(s['duplicate'] for s in slots):
        warnings.append('В графике есть повторяющиеся столбцы одной даты и времени. Объедините их в таблице перед назначением.')
    for slot in slots:
        cells = []
        for key, show in sorted(shows.items()):
            roles = []
            for role_key, role in show['roles'].items():
                actors = []
                for actor_key, actor_name in sorted(role['actors'].items()):
                    matches = actor_rows.get(actor_key, [])
                    raw = str(matches[0][1][slot['index']]).strip() if len(matches) == 1 and len(matches[0][1]) > slot['index'] else ''
                    value = norm(raw)
                    if len(matches) != 1:
                        status = 'unknown'
                        reason = 'Нет однозначной строки в графике'
                    elif value == 'да':
                        status, reason = 'yes', 'Свободен'
                    elif value == 'нет':
                        status, reason = 'no', 'Не может'
                    elif not value:
                        status, reason = 'unknown', 'Нет ответа'
                    elif norm(slot['assigned_show']) == key and value == role_key:
                        status, reason = 'assigned', 'Уже назначен на эту роль'
                    elif value in show['roles'] or slot['assigned_show']:
                        status, reason = 'busy', f'Назначение: {raw}'
                    else:
                        status, reason = 'unknown', f'Нужна проверка: {raw}'
                    actors.append({'name': actor_name, 'status': status, 'reason': reason})
                roles.append({'name': role['name'], 'actors': actors})
            suggested = match_roles(roles)
            possible = match_roles(roles, ('yes', 'assigned', 'unknown'))
            complete = bool(roles) and not show['incomplete'] and len(suggested) == len(roles)
            occupied = bool(slot['assigned_show']) and norm(slot['assigned_show']) != key
            status = 'ambiguous' if slot['duplicate'] else 'occupied' if occupied else 'ready' if complete else 'waiting' if roles and not show['incomplete'] and len(possible) == len(roles) else 'blocked'
            cells.append({'show': show['name'], 'status': status, 'covered': len(suggested),
                          'total': len(roles), 'roles': roles, 'suggested_cast': suggested,
                          'incomplete': show['incomplete'] or not bool(roles)})
        slot['shows'] = cells
        del slot['index']
    return {
        'month': month, 'shows': [s['name'] for _, s in sorted(shows.items())], 'slots': slots,
        'warnings': sorted(set(warnings)),
        'fingerprint': hashlib.sha256(json.dumps(source, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
    }


def assignment_updates(source, plan, column, show_name, cast):
    """Validate the reviewed complete cast and build the exact sheet writes."""
    slot = next((s for s in plan['slots'] if s['column'] == column), None)
    cell = next((s for s in slot['shows'] if s['show'] == show_name), None) if slot else None
    if not cell:
        raise ValueError('Дата или спектакль больше не найдены')
    if slot['duplicate']:
        raise ValueError('В графике несколько столбцов одной даты и времени. Сначала объедините их.')
    if slot['assigned_show']:
        raise ValueError('На эту дату уже назначен спектакль. Измените назначение в графике.')
    if cell['incomplete'] or set(cast) != {r['name'] for r in cell['roles']}:
        raise ValueError('Нужно закрыть все уникальные роли')
    if len({norm(actor) for actor in cast.values()}) != len(cast):
        raise ValueError('Один актёр не может играть две роли в одном спектакле')
    updates = [{'range': f"'График [составы]'!{column}2", 'values': [[show_name.upper()]]}]
    for role in cell['roles']:
        actor = next((a for a in role['actors'] if a['name'] == cast[role['name']]), None)
        if not actor or actor['status'] not in ('yes', 'assigned'):
            raise ValueError(f"Для роли «{role['name']}» нужен свободный исполнитель")
        row = next(index for index, values in enumerate(source['schedule'][2:], 3)
                   if values and norm(values[0]) == norm(actor['name']))
        updates.append({'range': f"'График [составы]'!{column}{row}", 'values': [[role['name']]]})
    return updates
