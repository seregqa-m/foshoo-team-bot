"""Conservative, persistent title grouping for presentation only."""
import re
import unicodedata
from collections import defaultdict
from datetime import datetime, timedelta
from threading import Lock

from core.time import local_now
from modules.theater.routing import match_show, saved_event_show
from .classification import classify_event
from .models import CalendarEvent, CalendarColorGroup, CalendarColorTitle

_group_lock = Lock()  # The deployment runs one worker; serialize its API threads.


def normalize_title(title):
    value = unicodedata.normalize('NFKC', title or '').casefold().replace('ё', 'е')
    value = ' '.join(re.findall(r'[^\W_]+', value))
    return re.sub(r'^(?:мастер класс|мастеркласс|м к)(?= |$)', 'мк', value)


def always_gray(title):
    return bool(re.search(r'\b(?:уборк\w*|аренд\w*|клининг\w*|musbooking)\b', title))


def similar_titles(left, right):
    """Normalized titles: >=90% similarity, <=2 edits, no numeric/name shortcuts."""
    if left == right:
        return True
    if min(len(left), len(right)) < 8:
        return False
    if re.findall(r'\d+', left) != re.findall(r'\d+', right):
        return False
    # A shared workshop prefix must never merge different teachers/surnames.
    if any(re.match(r'^(?:мк|интенсив)(?: |$)', name) for name in (left, right)):
        return False
    limit = min(2, max(len(left), len(right)) // 10)
    if abs(len(left) - len(right)) > limit:
        return False
    previous = list(range(len(right) + 1))
    for i, a in enumerate(left, 1):
        current = [i]
        for j, b in enumerate(right, 1):
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (a != b)))
        if min(current) > limit:
            return False
        previous = current
    return previous[-1] <= limit


def _eligible(db, event, aliases):
    kind = classify_event(event.title, aliases)['event_type']
    return kind != 'performance' and not (
        kind == 'rehearsal' and (saved_event_show(db, event) or match_show(event.title, aliases)))


def color_groups(db, aliases):
    """Return active groups, independent of the calendar request's date filters.

    Three distinct local dates in [-90, +60] days activate a group. Singleton
    identities are retained so future repeats and process restarts keep colors.
    Existing groups are never merged or renamed. A new spelling must match every
    member of exactly one group; ambiguous matches get a separate identity.
    """
    today = local_now().date()
    first = datetime.combine(today - timedelta(days=90), datetime.min.time())
    end = datetime.combine(today + timedelta(days=61), datetime.min.time())
    events = db.query(CalendarEvent).filter(
        CalendarEvent.is_cancelled == False,
        CalendarEvent.start_time >= first, CalendarEvent.start_time < end,
    ).all()
    days = defaultdict(set)
    labels = {}
    for event in events:
        title = normalize_title(event.title)
        if not title or always_gray(title) or not _eligible(db, event, aliases):
            continue
        days[title].add(event.start_time.date())
        labels.setdefault(title, ' '.join(event.title.split()))

    with _group_lock:
        groups = {group.id: group for group in db.query(CalendarColorGroup).all()}
        members = defaultdict(list)
        assigned = {}
        for entry in db.query(CalendarColorTitle).all():
            members[entry.group_id].append(entry.normalized_title)
            assigned[entry.normalized_title] = entry.group_id
        changed = False
        for title in sorted(days, key=lambda value: (-len(days[value]), value)):
            if title in assigned:
                continue
            matches = [group_id for group_id, titles in members.items()
                       if all(similar_titles(title, other) for other in titles)]
            if len(matches) == 1:
                group_id = matches[0]
            else:
                group = CalendarColorGroup(name=labels[title])
                db.add(group)
                db.flush()
                group_id = group.id
                groups[group_id] = group
            db.add(CalendarColorTitle(normalized_title=title, group_id=group_id))
            assigned[title] = group_id
            members[group_id].append(title)
            changed = True
        if changed:
            db.commit()
        group_days = defaultdict(set)
        for title, dates in days.items():
            group_days[assigned[title]].update(dates)
        return {title: {'color_group_id': group_id, 'color_group_name': groups[group_id].name}
                for title, group_id in assigned.items() if len(group_days[group_id]) >= 3}
