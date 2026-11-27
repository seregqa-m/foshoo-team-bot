"""Standard show windows in the theater's local timezone (no setup buffer)."""
from datetime import datetime, time, timedelta

from core.time import as_local
from .services import norm


PERFORMANCE_START_HOURS = {
    'small': (20, 20, 20, 20, 19, 19, 18),
    'large': (None, None, None, None, 19, 19, 18),
}


def show_format(name):
    return 'large' if norm(name) in ('цианистый калий', 'микрополь') else 'small'


def performance_window(day, name, kind=None, start_time=None):
    kind = kind or show_format(name)
    hour = PERFORMANCE_START_HOURS[kind][day.weekday()]
    if hour is None:
        return None
    start = as_local(datetime.combine(day, time.fromisoformat(start_time) if start_time else time(hour)))
    end = start + timedelta(minutes=180 if kind == 'large' else 90)
    if end > as_local(datetime.combine(day + timedelta(days=1), time())):
        raise ValueError('Показ должен завершиться не позже полуночи: ответы актёров проверяются на выбранный день.')
    return start, end


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
