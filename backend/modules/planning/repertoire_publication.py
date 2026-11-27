"""Superadmin preview/confirm publication with durable, idempotent event writes."""
import json
import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from config import GOOGLE_CALENDAR_ID, GOOGLE_CALENDAR_JSON, TIMEZONE
from core.database import get_db
from core.time import as_local, local_now
from modules.attendance.services import answer_lock
from modules.calendar.google_client import GoogleCalendarClient
from modules.calendar.services import CalendarService
from modules.calendar.models import CalendarEvent
from modules.calendar.classification import classify_event
from .models import RepertoireAffiche, RepertoirePublication
from .repertoire import RepertoireProblem, digest
from .repertoire_source import get_rules
from .repertoire_search import cached_variant, search_key
from .repertoire_affiche import LockRequest, save_revision, without_cast_assignments

logger = logging.getLogger(__name__)
router = APIRouter()


def require_superadmin(request: Request):
    if not getattr(request.state, 'is_superadmin', False):
        raise HTTPException(403, 'Закреплять и снимать закрепление афиши может только суперадминистратор')


def google_client():
    if not GOOGLE_CALENDAR_ID:
        raise HTTPException(503, 'Google Calendar не настроен')
    return GoogleCalendarClient(GOOGLE_CALENDAR_JSON)


def month_events(google, month):
    start = as_local(datetime.fromisoformat(month + '-01'))
    end = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    events, page = [], None
    while True:
        response = google.service.events().list(calendarId=GOOGLE_CALENDAR_ID, timeMin=start.isoformat(),
            timeMax=end.isoformat(), singleEvents=True, orderBy='startTime', pageToken=page).execute()
        events.extend(e for e in response.get('items', []) if e.get('status') != 'cancelled')
        page = response.get('nextPageToken')
        if not page:
            break
    google.sync_window = (start, end)
    return events


def pending_publication(db, month):
    return db.query(RepertoirePublication).filter(RepertoirePublication.month == month,
        RepertoirePublication.status.in_(['applying', 'partial'])).first()


def publication_data(row):
    payload = json.loads(row.payload)
    return {'id': row.id, 'status': row.status, 'month': row.month, 'actions': payload['actions'],
            'error': row.error, 'done': sum(a.get('done', False) for a in payload['actions']),
            'existing_count': sum(e['fixed'] for e in payload['variant']['entries'])}


def assert_no_publication(db, month):
    if pending_publication(db, month):
        raise HTTPException(409, 'Применение афиши не завершено. Суперадминистратору нужно продолжить сохранение календаря.')


@router.post('/repertoire/lock/preview', dependencies=[Depends(require_superadmin)])
def preview_publication(req: LockRequest, request: Request, db: Session = Depends(get_db)):
    from .repertoire_router import valid_month, snapshot, settings_lock
    valid_month(req.month)
    with settings_lock, answer_lock:
        assert_no_publication(db, req.month)
        if db.get(RepertoireAffiche, req.month):
            raise HTTPException(409, 'Афиша уже закреплена. Обновите план.')
        google = google_client()
        events = month_events(google, req.month)
        CalendarService(db, google).sync_from_google(events)
        source = snapshot(db, req.month, fresh=True)
        rules, revision, _ = get_rules(db, req.month, source['shows'])
        problem = RepertoireProblem(source, rules, local_now().date())
        if revision != req.expected_revision or source['fingerprint'] != req.expected_fingerprint or search_key(problem) != req.search_id:
            raise HTTPException(409, 'Календарь, ответы или параметры изменились. Обновите афишу и откройте подтверждение заново.')
        variant = cached_variant(req.search_id, req.variant_id)
        if variant is None:
            raise HTTPException(409, 'Вариант устарел. Обновите афишу.')
        actions = []
        for entry in variant['entries']:
            if entry['fixed']:
                continue
            targets = [e for e in events if as_local(CalendarService._parse_dt(e['start'])).date().isoformat() == entry['date']
                       and classify_event(e.get('summary', ''))['event_type'] == 'rehearsal']
            if any((CalendarService._parse_dt(e['end']) - timedelta(microseconds=1)).date().isoformat() != entry['date'] for e in targets):
                raise HTTPException(409, f'{entry["date"]}: репетиция длится несколько дней. Сначала разделите её в календаре, чтобы не изменить другие даты.')
            actions.append({'date': entry['date'], 'key': entry['key'], 'title': entry['name'] + ' [Спект]',
                'start_time': entry['start_time'], 'end_time': entry['end_time'], 'kind': 'replace' if targets else 'create',
                'targets': [{'id': e['id'], 'title': e.get('summary', ''), 'etag': e['etag'],
                    'start_time': e['start'].get('dateTime', e['start'].get('date')), 'end_time': e['end'].get('dateTime', e['end'].get('date')),
                    'location': e.get('location', ''), 'description': e.get('description', ''), 'all_day': 'date' in e['start'],
                    'recurring': bool(e.get('recurringEventId'))} for e in targets]})
        payload = {'variant': without_cast_assignments(variant), 'actions': actions, 'revision': revision, 'fingerprint': source['fingerprint'],
                   'source_fingerprint': source['source_fingerprint'], 'events': {e['id']: e['etag'] for e in events}}
        op_id = digest([request.state.telegram_user.id, req.month, payload])
        row = db.get(RepertoirePublication, op_id)
        if row is None:
            row = RepertoirePublication(id=op_id, month=req.month, actor_id=request.state.telegram_user.id,
                status='preview', payload=json.dumps(payload, ensure_ascii=False))
            db.add(row); db.commit()
        elif row.status == 'preview':
            row.created_at = datetime.utcnow()
            db.commit()
        return publication_data(row)


class ConfirmPublication(BaseModel):
    preview_id: str = Field(pattern=r'^[a-f0-9]{64}$')
    choices: dict[str, str] = Field(default_factory=dict, max_length=31)
    locations: dict[str, str] = Field(default_factory=dict, max_length=31)


def matches(event, body):
    if not event or event.get('status') == 'cancelled':
        return False
    try:
        return all((event.get(k) or '') == (body.get(k) or '') for k in ('summary', 'description', 'location')) and all(
            as_local(datetime.fromisoformat(event[k]['dateTime'])) == as_local(datetime.fromisoformat(body[k]['dateTime'])) for k in ('start', 'end'))
    except (KeyError, ValueError):
        return False


def preflight(events, payload):
    actual = {e['id']: e for e in events}
    affected = {a['event_id'] for a in payload['actions']}
    # Refuse unrelated external changes, including new events in previously empty dates.
    if {k: v['etag'] for k, v in actual.items() if k not in affected} != {k: v for k, v in payload['events'].items() if k not in affected}:
        raise HTTPException(409, 'Календарь изменился после подтверждения. Проверьте изменения; автоматическая перезапись остановлена.')
    for action in payload['actions']:
        event = actual.get(action['event_id'])
        if matches(event, action['body']):
            continue
        if action.get('done') or (action['kind'] == 'create' and event) or (action['kind'] == 'replace' and (not event or event.get('etag') != action['etag'])):
            raise HTTPException(409, f'{action["date"]}: событие изменено или удалено в календаре. Сохранение остановлено.')
    return actual


def mirror_event(db, event):
    row = db.query(CalendarEvent).filter_by(google_event_id=event['id']).first()
    if row is None:
        row = CalendarEvent(google_event_id=event['id']); db.add(row); db.flush()
    row.title, row.description, row.location = event.get('summary', ''), event.get('description', ''), event.get('location', '')
    row.start_time, row.end_time = CalendarService._parse_dt(event['start']), CalendarService._parse_dt(event['end'])
    row.is_all_day, row.is_cancelled = False, False
    row.google_html_link, row.recurring_event_id = event.get('htmlLink'), event.get('recurringEventId')
    row.last_synced = datetime.utcnow()
    row.poll_show_id, row.poll_show_title = None, None
    from modules.polling.models import Poll
    db.query(Poll).filter(Poll.calendar_event_id == row.id).update({'is_active': False})


@router.post('/repertoire/lock', dependencies=[Depends(require_superadmin)])
def confirm_publication(req: ConfirmPublication, request: Request, db: Session = Depends(get_db)):
    from .repertoire_router import snapshot, settings_lock
    from .router import _write_lock
    with settings_lock, _write_lock, answer_lock:
        db.expire_all()
        row = db.get(RepertoirePublication, req.preview_id)
        if row is None:
            raise HTTPException(404, 'Подтверждение не найдено')
        if row.status == 'complete':
            return publication_data(row)
        if row.status == 'stopped':
            raise HTTPException(409, 'Применение остановлено. Подготовьте новую афишу.')
        payload = json.loads(row.payload)
        google = google_client()
        events = month_events(google, row.month)
        source = snapshot(db, row.month, fresh=True)
        rules, revision, _ = get_rules(db, row.month, source['shows'])
        if row.status == 'preview':
            assert_no_publication(db, row.month)
            if row.actor_id != request.state.telegram_user.id or datetime.utcnow() - row.created_at > timedelta(minutes=15):
                raise HTTPException(409, 'Откройте подтверждение заново.')
            if db.get(RepertoireAffiche, row.month) or revision != payload['revision'] or source['fingerprint'] != payload['fingerprint']:
                raise HTTPException(409, 'Ответы, календарь или параметры изменились. Откройте подтверждение заново.')
            for action in payload['actions']:
                target = None
                if action['kind'] == 'replace':
                    target_id = req.choices.get(action['date'])
                    target = next((t for t in action['targets'] if t['id'] == target_id), None)
                    if not target:
                        raise HTTPException(422, f'{action["date"]}: выберите репетицию для замены')
                    action['event_id'], action['etag'] = target['id'], target['etag']
                else:
                    action['event_id'] = digest(['affiche', row.id, action['date']])
                location = target['location'] if target else req.locations.get(action['date'], '').strip()
                if not target and (not location or len(location) > 500):
                    raise HTTPException(422, f'{action["date"]}: укажите место нового показа (до 500 символов)')
                action['body'] = {'summary': action['title'], 'location': location,
                    'description': target['description'] if target else '',
                    'start': {'dateTime': action['start_time'], 'timeZone': TIMEZONE},
                    'end': {'dateTime': action['end_time'], 'timeZone': TIMEZONE}}
                if target and target['all_day']:
                    action['body']['start']['date'] = None
                    action['body']['end']['date'] = None
            preflight(events, payload)
            payload['revision'] = save_revision(db, row.month, rules, revision)
            row.status, row.payload = 'applying', json.dumps(payload, ensure_ascii=False)
            db.commit()
        else:
            if revision != payload['revision'] or source['source_fingerprint'] != payload['source_fingerprint']:
                raise HTTPException(409, 'Ответы или параметры изменились после начала записи. Требуется проверка уже применённых событий.')
        try:
            actual = preflight(events, payload)
            for action in payload['actions']:
                current = actual.get(action['event_id'])
                if matches(current, action['body']):
                    updated = current
                elif action['kind'] == 'replace':
                    updated = google.patch_event(GOOGLE_CALENDAR_ID, action['event_id'], action['body'], action['etag'])
                else:
                    updated = google.ensure_planned_event(GOOGLE_CALENDAR_ID, action['event_id'], action['body'])
                mirror_event(db, updated)
                action['done'] = True
                row.payload = json.dumps(payload, ensure_ascii=False)
                db.commit()
            saved = db.get(RepertoireAffiche, row.month)
            if saved is None:
                saved = RepertoireAffiche(month=row.month); db.add(saved)
            saved.payload = json.dumps(without_cast_assignments(payload['variant']), ensure_ascii=False)
            row.status, row.error = 'complete', None
            db.commit()
            return publication_data(row)
        except Exception as exc:
            db.rollback()
            row = db.get(RepertoirePublication, req.preview_id)
            row.status = 'partial'
            row.error = exc.detail if isinstance(exc, HTTPException) else 'Сохранение прервалось. Часть событий могла измениться. Продолжение сверит календарь и не создаст дубликатов.'
            db.commit()
            logger.warning('Repertoire publication incomplete: %s', row.id)
            return publication_data(row)


@router.post('/repertoire/lock/stop', dependencies=[Depends(require_superadmin)])
def stop_publication(req: ConfirmPublication, db: Session = Depends(get_db)):
    from .repertoire_router import settings_lock
    from .router import _write_lock
    with settings_lock, _write_lock, answer_lock:
        row = db.get(RepertoirePublication, req.preview_id, populate_existing=True)
        if not row or row.status not in ('applying', 'partial', 'stopped'):
            raise HTTPException(409, 'Нет незавершённого применения')
        if row.status == 'stopped':
            return publication_data(row)
        google = google_client()
        events = month_events(google, row.month)
        CalendarService(db, google).sync_from_google(events)
        payload = json.loads(row.payload)
        actual = {e['id']: e for e in events}
        for action in payload['actions']:
            action['done'] = matches(actual.get(action['event_id']), action['body'])
            if action['done']:
                mirror_event(db, actual[action['event_id']])
        rules, revision, _ = get_rules(db, row.month, [])
        save_revision(db, row.month, rules, revision)
        row.status, row.error, row.payload = 'stopped', None, json.dumps(payload, ensure_ascii=False)
        db.commit()
        return publication_data(row)
