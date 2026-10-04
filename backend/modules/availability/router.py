import asyncio
import json
import hashlib
from core.time import local_now
import logging
import os
from calendar import monthrange
from datetime import date, datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from core.database import get_db
from config import GOOGLE_CALENDAR_JSON, GOOGLE_SHEETS_ID, ADMIN_ID
from modules.theater.routing import campaign_destinations, cast_usernames, poll_link
from modules.attendance.services import answered_usernames, option_day
from .models import AvailabilityCampaign, AvailabilityPoll, AvailabilityPollOption, AvailabilityVote
from modules.calendar.models import CalendarEvent
from modules.calendar.classification import is_troupe_event
from modules.notifications.models import NotificationSetting

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/availability", tags=["availability"])


def _date_label(dt: date | datetime) -> str:
    """datetime → строка для опции опроса, напр. 'сб 17 мая'"""
    from babel.dates import format_date
    day_name = format_date(dt, 'EE', locale='ru_RU').rstrip('.')
    month_day = format_date(dt, 'd MMM', locale='ru_RU')
    return f"{day_name} {month_day}"


def _get_troupe_filter(db: Session) -> str:
    s = db.query(NotificationSetting).filter(NotificationSetting.user_id == ADMIN_ID).first()
    return (s.troupe_filter if s and s.troupe_filter else None) or "труппа 1"


@router.get("/next-month-events")
def get_next_month_events(db: Session = Depends(get_db), month: str | None = None):
    """События выбранного месяца; по умолчанию — следующего (не спектакли)."""
    today = local_now().date()
    try:
        first_next = date.fromisoformat(month + "-01") if month is not None else (
            today.replace(day=1) + timedelta(days=32)
        ).replace(day=1)
    except ValueError as exc:
        raise HTTPException(422, "Месяц должен быть в формате ГГГГ-ММ") from exc
    last_next = first_next.replace(day=monthrange(first_next.year, first_next.month)[1])

    troupe_filter = _get_troupe_filter(db)

    show_names_lower = []
    if GOOGLE_SHEETS_ID and os.path.exists(GOOGLE_CALENDAR_JSON):
        try:
            from sheets_client import SheetsClient
            show_names_lower = [s.lower() for s in SheetsClient(
                GOOGLE_CALENDAR_JSON, GOOGLE_SHEETS_ID
            ).get_show_names()]
        except Exception:
            pass

    events = db.query(CalendarEvent).filter(
        CalendarEvent.is_cancelled == False,
        CalendarEvent.start_time >= datetime.combine(first_next, datetime.min.time()),
        CalendarEvent.start_time <= datetime.combine(last_next, datetime.max.time()),
    ).order_by(CalendarEvent.start_time).all()

    result = []
    for e in events:
        if not is_troupe_event(e.title, show_names_lower, troupe_filter):
            continue
        result.append({
            "id": e.id,
            "title": e.title,
            "start_time": e.start_time.isoformat(),
            "date_label": _date_label(e.start_time),
        })
    return {"events": result, "month": first_next.strftime("%Y-%m")}


@router.get("/check-dates")
def check_dates(event_ids: str = "", dates: str = "", db: Session = Depends(get_db)):
    """Проверить столбцы для дат ISO; event_ids поддерживается для старых клиентов."""
    try:
        if dates:
            selected = sorted({date.fromisoformat(value) for value in dates.split(",")})
            dts = [datetime.combine(value, datetime.min.time()) for value in selected]
        else:
            ids = [int(x) for x in event_ids.split(",") if x.strip()]
            events = db.query(CalendarEvent).filter(CalendarEvent.id.in_(ids)).all()
            dts = [e.start_time for e in events]
    except ValueError as exc:
        raise HTTPException(422, "Некорректные даты") from exc
    if not GOOGLE_SHEETS_ID or not os.path.exists(GOOGLE_CALENDAR_JSON):
        return {"missing": [], "all_ok": True}

    try:
        from sheets_client import SheetsClient
        client = SheetsClient(GOOGLE_CALENDAR_JSON, GOOGLE_SHEETS_ID)
        missing_dts = client.check_dates_exist(dts)
        missing_labels = [_date_label(dt) for dt in missing_dts]
    except Exception as e:
        logger.error(f"check_dates failed: {e}")
        return {"missing": [], "all_ok": True}

    return {"missing": missing_labels, "all_ok": len(missing_labels) == 0}


@router.get("/current")
def get_current(db: Session = Depends(get_db), campaign_id: int | None = None):
    """Текущая кампания с опросами и количеством проголосовавших."""
    campaign = _find_campaign(db, campaign_id)
    if not campaign:
        return {"campaign": None}

    polls_data = []
    for poll in campaign.polls:
        voters = {v.username for v in poll.votes if v.username}
        polls_data.append({
            "id": poll.id,
            "telegram_poll_id": poll.telegram_poll_id,
            "telegram_message_id": poll.telegram_message_id,
            "telegram_chat_id": poll.telegram_chat_id,
            "show_names": json.loads(poll.show_names or campaign.show_names),
            "delivery_state": poll.delivery_state,
            "tg_link": poll_link(poll.telegram_chat_id, poll.telegram_message_id),
            "voter_count": len(voters),
            "options": [
                {"option_index": o.option_index, "date_label": o.date_label,
                 "calendar_event_id": o.calendar_event_id,
                 "date": o.selected_date.isoformat() if o.selected_date else None}
                for o in sorted(poll.options, key=lambda x: x.option_index)
            ],
        })

    return {
        "campaign": {
            "id": campaign.id,
            "month": campaign.month,
            "show_names": json.loads(campaign.show_names),
            "created_at": campaign.created_at.isoformat(),
            "polls": polls_data,
        }
    }


def _find_campaign(db, campaign_id=None):
    if campaign_id is not None:
        campaign = db.get(AvailabilityCampaign, campaign_id)
        if not campaign:
            raise HTTPException(404, 'Опрос занятости не найден')
        return campaign
    return db.query(AvailabilityCampaign).order_by(AvailabilityCampaign.id.desc()).first()


def _campaign_non_voters(db, campaign):
    if not GOOGLE_SHEETS_ID or not os.path.exists(GOOGLE_CALENDAR_JSON):
        raise HTTPException(503, 'Google Sheets не настроен')
    from sheets_client import SheetsClient
    client = SheetsClient(GOOGLE_CALENDAR_JSON, GOOGLE_SHEETS_ID)
    destinations = campaign_destinations(db, json.loads(campaign.show_names))
    dates = {option_day(o, db) for p in campaign.polls for o in p.options} - {None}
    answered = {day: answered_usernames(db, day) for day in dates}
    try:
        return {chat: sorted(username for username in cast_usernames(db, names, client)
                             if any(username not in answered[day] for day in dates))
                for chat, names in destinations.items()}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, 'Не удалось прочитать состав') from exc


@router.get('/non-voters')
def get_non_voters(db: Session = Depends(get_db), campaign_id: int | None = None):
    campaign = _find_campaign(db, campaign_id)
    groups = _campaign_non_voters(db, campaign) if campaign and campaign.polls else {}
    return {'non_voters': sorted({u for users in groups.values() for u in users}),
            'chats': [{'chat_id': chat, 'non_voters': users} for chat, users in groups.items()]}


@router.post('/ping-non-voters')
async def ping_non_voters(db: Session = Depends(get_db), campaign_id: int | None = None):
    from bot import bot
    campaign = _find_campaign(db, campaign_id)
    if not campaign:
        raise HTTPException(404, 'Нет активного опроса')
    groups = await asyncio.to_thread(_campaign_non_voters, db, campaign)
    sent, errors = set(), []
    for chat, users in groups.items():
        if not users:
            continue
        publications = [p for p in campaign.polls if p.telegram_chat_id == chat and p.telegram_message_id]
        if not publications:
            errors.append({'chat_id': chat, 'error': 'В этом чате ещё нет опроса. Запустите его для выбранных дат.'})
            continue
        links = [link for p in publications if (link := poll_link(chat, p.telegram_message_id))]
        message = f'Отметьте занятость на {campaign.month}!\n' + ' '.join('@' + u for u in users)
        if links:
            message += '\n\n' + '\n'.join(links)
        try:
            await bot.send_message(chat_id=chat, text=message)
            sent.update(users)
        except Exception:
            logger.exception('Availability reminder failed for chat %s', chat)
            errors.append({'chat_id': chat, 'error': 'Не удалось отправить напоминание'})
    return {'status': 'partial' if errors else 'sent' if sent else 'all_answered', 'count': len(sent), 'errors': errors}


class CreateCampaignRequest(BaseModel):
    show_names: list[str]
    event_ids: list[int] | None = None
    dates: list[date] | None = None
    retry_unconfirmed: bool = False


def _campaign_dates(req: CreateCampaignRequest, db: Session):
    """Freeze one option per date, independent of later calendar edits."""
    if req.dates is not None and req.event_ids is not None:
        raise HTTPException(400, "Передайте даты или события, не оба списка")
    if req.dates is not None:
        selected = [(d, None, "") for d in sorted(set(req.dates))]
    else:
        ids = set(req.event_ids or [])
        events = db.query(CalendarEvent).filter(
            CalendarEvent.id.in_(ids), CalendarEvent.is_cancelled == False,
        ).order_by(CalendarEvent.start_time, CalendarEvent.id).all()
        if len(events) != len(ids):
            raise HTTPException(409, "Некоторые события удалены или отменены")
        by_date = {}
        for event in events:
            by_date.setdefault(event.start_time.date(), (event.start_time.date(), event.id, event.title))
        selected = list(by_date.values())
    if not selected:
        raise HTTPException(400, "Не выбраны даты")
    if len(selected) > 31 or len({d.strftime("%Y-%m") for d, _, _ in selected}) != 1:
        raise HTTPException(400, "Выберите даты одного месяца (максимум 31)")
    return selected


@router.post('/campaign')
async def create_campaign(req: CreateCampaignRequest, db: Session = Depends(get_db)):
    from bot import bot
    from babel.dates import format_date
    from modules.polling.delivery import delivery_lock, send_publication
    if not req.show_names:
        raise HTTPException(400, 'Не выбраны спектакли')
    selected = _campaign_dates(req, db)
    destinations = campaign_destinations(db, req.show_names)
    month = selected[0][0].strftime('%Y-%m')
    key = hashlib.sha256(json.dumps({'dates': [d.isoformat() for d, _, _ in selected],
                                    'chats': destinations}, sort_keys=True).encode()).hexdigest()
    async with delivery_lock:
        campaign = db.query(AvailabilityCampaign).filter_by(request_key=key).order_by(AvailabilityCampaign.id.desc()).first()
        if not campaign:
            await asyncio.to_thread(_ensure_campaign_columns, [
                (datetime.combine(d, datetime.min.time()), title) for d, _, title in selected])
            campaign = AvailabilityCampaign(month=month, request_key=key,
                show_names=json.dumps(sorted({name for names in destinations.values() for name in names}), ensure_ascii=False))
            db.add(campaign)
            db.flush()
            for chat, names in destinations.items():
                for start in range(0, len(selected), 9):
                    poll = AvailabilityPoll(campaign_id=campaign.id, telegram_chat_id=chat,
                        show_names=json.dumps(names, ensure_ascii=False), delivery_state='pending')
                    db.add(poll)
                    db.flush()
                    for i, (day, event_id, _) in enumerate(selected[start:start+9]):
                        db.add(AvailabilityPollOption(poll_id=poll.id, option_index=i,
                            calendar_event_id=event_id, selected_date=day, date_label=_date_label(day)))
            db.commit()
        errors = []
        for poll in campaign.polls:
            try:
                if poll.telegram_message_id:
                    continue
                db.expire_all()
                current = campaign_destinations(db, json.loads(poll.show_names or campaign.show_names))
                if set(current) != {poll.telegram_chat_id}:
                    raise HTTPException(409, 'Чат спектакля изменился. Обновите настройки и запустите опрос заново.')
                if req.retry_unconfirmed and not poll.telegram_message_id and poll.delivery_state in ('sending', 'uncertain'):
                    poll.delivery_state = 'pending'
                    db.commit()
                await send_publication(db, bot, poll,
                    question=f"В какие даты вы свободны? {format_date(selected[0][0], 'MMMM yyyy', locale='ru_RU')}",
                    options=[o.date_label for o in sorted(poll.options, key=lambda o: o.option_index)] + ['Ни одна из дат'],
                    multiple=True)
            except HTTPException as exc:
                errors.append({'chat_id': poll.telegram_chat_id, 'poll_id': poll.id,
                               'delivery_state': poll.delivery_state, 'error': exc.detail})
        return {'status': 'partial' if errors else 'sent', 'campaign_id': campaign.id,
                'month': month, 'polls_count': sum(bool(p.telegram_message_id) for p in campaign.polls),
                'events_count': len(selected), 'errors': errors}


def _ensure_campaign_columns(events):
    if not GOOGLE_SHEETS_ID or not os.path.exists(GOOGLE_CALENDAR_JSON):
        raise HTTPException(503, "Google Sheets не настроен")
    from sheets_client import SheetsClient
    SheetsClient(GOOGLE_CALENDAR_JSON, GOOGLE_SHEETS_ID).ensure_schedule_columns(events)
