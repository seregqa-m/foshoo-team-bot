"""Standard show windows in the theater's local timezone (no setup buffer)."""
from datetime import datetime, time, timedelta

from core.time import as_local
from .services import norm


def show_format(name):
    return 'large' if norm(name) in ('цианистый калий', 'микрополь') else 'small'


def performance_window(day, name, kind=None):
    kind = kind or show_format(name)
    weekday = day.weekday()
    if kind == 'large' and weekday < 4:
        return None
    hour = 20 if weekday < 4 else 19 if weekday == 4 or kind == 'small' else 18
    start = as_local(datetime.combine(day, time(hour)))
    return start, start + timedelta(minutes=180 if kind == 'large' else 90)


def calendar_conflicts(events, start, end):
    return [event for event in events
            if as_local(datetime.fromisoformat(event['start_time'])) < end
            and as_local(datetime.fromisoformat(event['end_time'])) > start]


def conflict_reason(events):
    labels = []
    for event in events:
        start, end = (as_local(datetime.fromisoformat(event[field])) for field in ('start_time', 'end_time'))
        when = 'весь день' if event.get('all_day') else (
            f'{start:%H:%M}–{end:%H:%M}' if start.date() == end.date() else f'{start:%d.%m %H:%M}–{end:%d.%m %H:%M}')
        labels.append(f'{event["title"]} ({when})')
    return 'Пересечение по времени: ' + '; '.join(labels)
