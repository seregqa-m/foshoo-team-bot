"""Small RFC 5545 feed: stable occurrence IDs, UTC times and UTF-8 folding."""
import base64
from datetime import timezone
from urllib.parse import quote, urlsplit

from config import GOOGLE_CALENDAR_ID
from core.time import as_local


def event_url(event):
    link = event.google_html_link or ''
    parsed = urlsplit(link)
    if parsed.scheme == 'https' and parsed.hostname == 'calendar.google.com':
        return link
    if event.google_event_id and GOOGLE_CALENDAR_ID:
        eid = base64.urlsafe_b64encode(f'{event.google_event_id} {GOOGLE_CALENDAR_ID}'.encode()).decode().rstrip('=')
        return 'https://calendar.google.com/calendar/event?eid=' + quote(eid)
    return None


def text_value(value):
    return (str(value or '').replace('\\', '\\\\').replace('\r\n', '\n').replace('\r', '\n')
            .replace('\n', '\\n').replace(';', '\\;').replace(',', '\\,'))


def fold(line):
    # Limits are octets, including the space that starts a continuation line.
    result, part = [], ''
    for char in line:
        if len((part + char).encode('utf-8')) > 75:
            result.append(part)
            part = ' '
        part += char
    return '\r\n'.join(result + [part])


def render_calendar(events, name='FoShoo'):
    lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//FoShoo//Shared Calendar//RU',
             'CALSCALE:GREGORIAN', 'X-WR-CALNAME:' + text_value(name),
             'REFRESH-INTERVAL;VALUE=DURATION:PT1H', 'X-PUBLISHED-TTL:PT1H']
    for event in events:
        stamp = (event.updated_at or event.created_at).replace(tzinfo=timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        lines += ['BEGIN:VEVENT', f'UID:calendar-event-{event.id}@foshoo',
                  f'DTSTAMP:{stamp}', f'LAST-MODIFIED:{stamp}',
                  'SUMMARY:' + text_value(event.title)]
        for field, dt in [('DTSTART', event.start_time), ('DTEND', event.end_time)]:
            if event.is_all_day:
                lines.append(f'{field};VALUE=DATE:{as_local(dt):%Y%m%d}')
            else:
                lines.append(f'{field}:{as_local(dt).astimezone(timezone.utc):%Y%m%dT%H%M%SZ}')
        if event.location:
            lines.append('LOCATION:' + text_value(event.location))
        # Do not expose descriptions: they can contain cast details/private notes.
        if event.is_cancelled:
            lines.append('STATUS:CANCELLED')
        else:
            lines.append('STATUS:CONFIRMED')
        lines.append('END:VEVENT')
    lines.append('END:VCALENDAR')
    return '\r\n'.join(fold(line) for line in lines) + '\r\n'
