import hashlib
import json
import logging
import os
from datetime import date, datetime, timedelta
from threading import Lock

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from config import GOOGLE_CALENDAR_JSON, GOOGLE_CALENDAR_ID, GOOGLE_SHEETS_ID, TIMEZONE
from core.database import get_db
from core.time import local_now, as_local
from sheets_client import SheetsClient
from modules.calendar.google_client import GoogleCalendarClient
from modules.calendar.models import CalendarEvent
from .models import PlanningAssignment
from .services import build_plan, assignment_updates

logger = logging.getLogger(__name__)
_write_lock = Lock()


def require_admin(request: Request):
    if not getattr(request.state, 'is_admin', False):
        raise HTTPException(403, 'Планирование составов доступно администратору')


router = APIRouter(prefix='/api/planning', tags=['planning'], dependencies=[Depends(require_admin)])


def get_client():
    if not GOOGLE_SHEETS_ID or not os.path.exists(GOOGLE_CALENDAR_JSON):
        raise HTTPException(503, 'Google Sheets не настроен')
    return SheetsClient(GOOGLE_CALENDAR_JSON, GOOGLE_SHEETS_ID)


def read_plan(client, month):
    try:
        source = client.get_planning_data()
        return source, build_plan(source, month)
    except Exception as exc:
        logger.exception('Cannot read cast planning')
        raise HTTPException(502, 'Не удалось прочитать график и составы. Попробуйте обновить.') from exc


@router.get('')
def get_planning(month: str | None = None, db: Session = Depends(get_db)):
    if month is None:
        month = (local_now().date().replace(day=1) + timedelta(days=32)).strftime('%Y-%m')
    try:
        date.fromisoformat(month + '-01')
    except ValueError as exc:
        raise HTTPException(422, 'Месяц должен быть в формате ГГГГ-ММ') from exc
    plan = read_plan(get_client(), month)[1]
    for op in db.query(PlanningAssignment).filter_by(month=month).all():
        slot = next((s for s in plan['slots'] if s['column'] == op.column), None)
        if slot:
            slot['operation'] = {'status': op.status, **json.loads(op.payload)['request']}
    plan['timezone'] = TIMEZONE
    return plan


class AssignRequest(BaseModel):
    month: str = Field(pattern=r'^\d{4}-\d{2}$')
    column: str = Field(pattern=r'^[A-Z]+$')
    show_name: str
    cast: dict[str, str]
    expected_fingerprint: str
    start_time: datetime
    end_time: datetime
    location: str = Field(min_length=1, max_length=500)


def _sheet_writes_applied(source, updates):
    from sheets_client import _col_num_to_letter
    import re
    for update in updates:
        column, row = re.search(r'!([A-Z]+)(\d+)$', update['range']).groups()
        values = source['schedule'][int(row) - 1] if len(source['schedule']) >= int(row) else []
        index = next((i for i in range(len(values)) if _col_num_to_letter(i + 1) == column), None)
        if index is None or values[index] != update['values'][0][0]:
            return False
    return True


@router.post('/assign')
def assign_show(req: AssignRequest, db: Session = Depends(get_db)):
    try:
        date.fromisoformat(req.month + '-01')
    except ValueError as exc:
        raise HTTPException(422, 'Некорректный месяц') from exc
    start, end = as_local(req.start_time), as_local(req.end_time)
    if end <= start or end - start > timedelta(days=1) or not req.location.strip():
        raise HTTPException(422, 'Проверьте время начала, окончания и место')
    if not GOOGLE_CALENDAR_ID:
        raise HTTPException(503, 'Google Calendar не настроен')
    request_data = {**req.model_dump(mode='json', exclude={'expected_fingerprint'}),
                    'start_time': start.isoformat(), 'end_time': end.isoformat(), 'location': req.location.strip()}
    operation_id = hashlib.sha256(f'{GOOGLE_SHEETS_ID}:{GOOGLE_CALENDAR_ID}:{req.month}:{req.column}'.encode()).hexdigest()
    with _write_lock:
        op = db.get(PlanningAssignment, operation_id)
        if op and json.loads(op.payload)['request'] != request_data:
            raise HTTPException(409, 'Для этой даты уже начато назначение. Обновите сводку и завершите его.')
        if op and op.status == 'complete':
            return {'status': 'assigned', 'show_name': req.show_name}
        client = get_client()
        source, plan = read_plan(client, req.month)
        slot = next((s for s in plan['slots'] if s['column'] == req.column), None)
        if not slot or start.date().isoformat() != slot['date']:
            raise HTTPException(409, 'Дата события не совпадает с выбранной датой графика')
        if op:
            saved = json.loads(op.payload)
            updates = saved['updates']
            if plan['fingerprint'] != saved['fingerprint'] and not _sheet_writes_applied(source, updates):
                raise HTTPException(409, 'График изменился после начала записи. Событие могло быть создано: проверьте его и состав в таблице.')
        else:
            if req.expected_fingerprint != plan['fingerprint']:
                raise HTTPException(409, 'График или ответы изменились. Обновите сводку и проверьте состав заново.')
            try:
                updates = assignment_updates(source, plan, req.column, req.show_name, req.cast)
            except ValueError as exc:
                raise HTTPException(409, str(exc)) from exc
            op = PlanningAssignment(id=operation_id, month=req.month, column=req.column,
                payload=json.dumps({'request': request_data, 'updates': updates, 'fingerprint': plan['fingerprint']}, ensure_ascii=False), status='prepared')
            db.add(op)
            db.commit()
        event_data = {
            'summary': req.show_name, 'location': req.location.strip(),
            'description': 'Состав:\n' + '\n'.join(f'{role}: {actor}' for role, actor in req.cast.items()),
            'start': {'dateTime': start.isoformat(), 'timeZone': TIMEZONE},
            'end': {'dateTime': end.isoformat(), 'timeZone': TIMEZONE},
        }
        try:
            google = GoogleCalendarClient(GOOGLE_CALENDAR_JSON)
            google.ensure_planned_event(GOOGLE_CALENDAR_ID, operation_id, event_data)
            event = db.query(CalendarEvent).filter_by(google_event_id=operation_id).first()
            if not event:
                event = CalendarEvent(google_event_id=operation_id, title=req.show_name, start_time=start,
                    end_time=end, location=req.location.strip(), description=event_data['description'], last_synced=datetime.utcnow())
                db.add(event)
            op.status = 'calendar_created'
            db.commit()
            latest_source, latest_plan = read_plan(client, req.month)
            if not _sheet_writes_applied(latest_source, updates):
                if latest_plan['fingerprint'] != json.loads(op.payload)['fingerprint']:
                    raise HTTPException(409, 'Событие создано, но ответы в графике изменились. Проверьте состав и событие перед дальнейшими действиями.')
                client.api.values().batchUpdate(spreadsheetId=client.spreadsheet_id,
                    body={'valueInputOption': 'RAW', 'data': updates}).execute()
            op.status = 'complete'
            db.commit()
        except HTTPException:
            db.rollback()
            raise
        except Exception as exc:
            db.rollback()
            logger.exception('Cast assignment incomplete')
            raise HTTPException(502, 'Сохранение не завершено. Обновите сводку и нажмите «Продолжить сохранение»: повтор не создаст второе событие.') from exc
    return {'status': 'assigned', 'show_name': req.show_name}
