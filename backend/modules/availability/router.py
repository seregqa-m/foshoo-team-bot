import json
import logging
import os
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from core.database import get_db
from config import GROUP_CHAT_ID, GOOGLE_CALENDAR_JSON, GOOGLE_SHEETS_ID, ADMIN_ID
from .models import AvailabilityCampaign, AvailabilityPoll, AvailabilityPollOption, AvailabilityVote
from modules.calendar.models import CalendarEvent
from modules.notifications.models import NotificationSetting

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/availability", tags=["availability"])


def _date_label(dt: datetime) -> str:
    """datetime → строка для опции опроса, напр. 'сб 17 мая'"""
    from babel.dates import format_date
    day_name = format_date(dt, 'EE', locale='ru_RU').rstrip('.')
    month_day = format_date(dt, 'd MMM', locale='ru_RU')
    return f"{day_name} {month_day}"


def _get_troupe_filter(db: Session) -> str:
    s = db.query(NotificationSetting).filter(NotificationSetting.user_id == ADMIN_ID).first()
    return (s.troupe_filter if s and s.troupe_filter else None) or "труппа 1"


@router.get("/next-month-events")
async def get_next_month_events(db: Session = Depends(get_db)):
    """События следующего месяца для труппы (не спектакли)."""
    today = datetime.utcnow().date()
    first_next = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
    last_next = (first_next + timedelta(days=32)).replace(day=1) - timedelta(days=1)

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
        CalendarEvent.start_time >= datetime.combine(first_next, datetime.min.time()),
        CalendarEvent.start_time <= datetime.combine(last_next, datetime.max.time()),
    ).order_by(CalendarEvent.start_time).all()

    result = []
    for e in events:
        t = e.title.lower()
        if troupe_filter not in t:
            continue
        if show_names_lower and any(s in t for s in show_names_lower):
            continue
        result.append({
            "id": e.id,
            "title": e.title,
            "start_time": e.start_time.isoformat(),
            "date_label": _date_label(e.start_time),
        })
    return {"events": result, "month": first_next.strftime("%Y-%m")}


@router.get("/check-dates")
async def check_dates(event_ids: str, db: Session = Depends(get_db)):
    """Проверить что для переданных event_ids есть столбцы в таблице занятости.
    event_ids — строка с id через запятую."""
    if not GOOGLE_SHEETS_ID or not os.path.exists(GOOGLE_CALENDAR_JSON):
        return {"missing": [], "all_ok": True}

    ids = [int(x) for x in event_ids.split(",") if x.strip()]
    events = db.query(CalendarEvent).filter(CalendarEvent.id.in_(ids)).all()

    try:
        from sheets_client import SheetsClient
        client = SheetsClient(GOOGLE_CALENDAR_JSON, GOOGLE_SHEETS_ID)
        missing_dts = client.check_dates_exist([e.start_time for e in events])
        missing_labels = [_date_label(dt) for dt in missing_dts]
    except Exception as e:
        logger.error(f"check_dates failed: {e}")
        return {"missing": [], "all_ok": True}

    return {"missing": missing_labels, "all_ok": len(missing_labels) == 0}


@router.get("/current")
async def get_current(db: Session = Depends(get_db)):
    """Текущая кампания с опросами и количеством проголосовавших."""
    campaign = db.query(AvailabilityCampaign).order_by(
        AvailabilityCampaign.id.desc()
    ).first()
    if not campaign:
        return {"campaign": None}

    polls_data = []
    for poll in campaign.polls:
        voters = {v.username for v in poll.votes if v.username}
        polls_data.append({
            "id": poll.id,
            "telegram_poll_id": poll.telegram_poll_id,
            "telegram_message_id": poll.telegram_message_id,
            "voter_count": len(voters),
            "options": [
                {"option_index": o.option_index, "date_label": o.date_label,
                 "calendar_event_id": o.calendar_event_id}
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


@router.get("/non-voters")
async def get_non_voters(db: Session = Depends(get_db)):
    """Список usernames из состава выбранных спектаклей, кто не ответил хотя бы на один опрос."""
    campaign = db.query(AvailabilityCampaign).order_by(
        AvailabilityCampaign.id.desc()
    ).first()
    if not campaign or not campaign.polls:
        return {"non_voters": []}

    show_names = json.loads(campaign.show_names)

    if not GOOGLE_SHEETS_ID or not os.path.exists(GOOGLE_CALENDAR_JSON):
        return {"non_voters": []}

    try:
        from sheets_client import SheetsClient
        client = SheetsClient(GOOGLE_CALENDAR_JSON, GOOGLE_SHEETS_ID)
        mapping = client.get_actor_mapping()  # {username: name}
        cast_usernames: set[str] = set()
        for show in show_names:
            cast_names = {n.lower() for n in client.get_show_cast(show)}
            name_to_uname = {name.lower(): uname for uname, name in mapping.items()}
            cast_usernames |= {name_to_uname[n] for n in cast_names if n in name_to_uname}
    except Exception as e:
        logger.error(f"non_voters cast lookup failed: {e}")
        return {"non_voters": []}

    non_voters = []
    for uname in cast_usernames:
        for poll in campaign.polls:
            voted = any(v.username and v.username.lower() == uname for v in poll.votes)
            if not voted:
                non_voters.append(uname)
                break

    return {"non_voters": sorted(non_voters)}


class CreateCampaignRequest(BaseModel):
    show_names: list[str]
    event_ids: list[int]


@router.post("/campaign")
async def create_campaign(req: CreateCampaignRequest, db: Session = Depends(get_db)):
    """Удалить старую кампанию, создать новую, отправить опросы в Telegram."""
    from bot import bot
    from babel.dates import format_date

    if not GROUP_CHAT_ID:
        raise HTTPException(status_code=400, detail="GROUP_CHAT_ID не настроен")
    if not req.event_ids:
        raise HTTPException(status_code=400, detail="Не выбраны даты")
    if not req.show_names:
        raise HTTPException(status_code=400, detail="Не выбраны спектакли")
    if len(req.event_ids) > 20:
        raise HTTPException(status_code=400, detail="Слишком много дат (максимум 20)")

    events = db.query(CalendarEvent).filter(
        CalendarEvent.id.in_(req.event_ids)
    ).order_by(CalendarEvent.start_time).all()

    if not events:
        raise HTTPException(status_code=404, detail="События не найдены")

    # Удалить старую кампанию
    old = db.query(AvailabilityCampaign).order_by(AvailabilityCampaign.id.desc()).first()
    if old:
        db.delete(old)
        db.flush()

    month = events[0].start_time.strftime("%Y-%m")
    month_label = format_date(events[0].start_time, "MMMM yyyy", locale="ru_RU")

    campaign = AvailabilityCampaign(
        month=month,
        show_names=json.dumps(req.show_names, ensure_ascii=False),
    )
    db.add(campaign)
    db.flush()

    # Разбить на батчи по 10 (Telegram poll limit)
    batches = [events[i:i+10] for i in range(0, len(events), 10)]
    poll_suffix = f" (часть {{}}/{len(batches)})" if len(batches) > 1 else ""

    for batch_idx, batch in enumerate(batches):
        options = [_date_label(e.start_time) for e in batch]
        question = f"Отметьте даты когда вы свободны для спектаклей — {month_label}" + (
            poll_suffix.format(batch_idx + 1) if poll_suffix else ""
        )

        try:
            message = await bot.send_poll(
                chat_id=GROUP_CHAT_ID,
                question=question,
                options=options,
                is_anonymous=False,
                allows_multiple_answers=True,
            )
        except Exception as e:
            db.rollback()
            raise HTTPException(status_code=502, detail=f"Ошибка отправки в Telegram: {e}")

        poll = AvailabilityPoll(
            campaign_id=campaign.id,
            telegram_poll_id=message.poll.id,
            telegram_message_id=message.message_id,
        )
        db.add(poll)
        db.flush()

        for i, event in enumerate(batch):
            db.add(AvailabilityPollOption(
                poll_id=poll.id,
                option_index=i,
                calendar_event_id=event.id,
                date_label=_date_label(event.start_time),
            ))

    db.commit()
    return {"status": "sent", "month": month, "polls_count": len(batches)}
