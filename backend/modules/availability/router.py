import asyncio
import json
from core.time import local_now
import logging
import os
from calendar import monthrange
from datetime import date, datetime, timedelta
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
def get_current(db: Session = Depends(get_db)):
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


@router.get("/non-voters")
def get_non_voters(db: Session = Depends(get_db)):
    """Список usernames из состава выбранных спектаклей, кто не ответил хотя бы на один опрос."""
    campaign = db.query(AvailabilityCampaign).order_by(
        AvailabilityCampaign.id.desc()
    ).first()
    if not campaign or not campaign.polls:
        return {"non_voters": []}

    show_names = json.loads(campaign.show_names)

    if not GOOGLE_SHEETS_ID or not os.path.exists(GOOGLE_CALENDAR_JSON):
        raise HTTPException(503, "Google Sheets не настроен")

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
        raise HTTPException(502, "Не удалось прочитать состав") from e

    non_voters = []
    for uname in cast_usernames:
        for poll in campaign.polls:
            voted = any(v.username and v.username.lower() == uname for v in poll.votes)
            if not voted:
                non_voters.append(uname)
                break

    return {"non_voters": sorted(non_voters)}


@router.post("/ping-non-voters")
async def ping_non_voters(db: Session = Depends(get_db)):
    """Отправить в чат напоминание с тегами тех, кто не ответил на опрос занятости."""
    from bot import bot
    from babel.dates import format_date

    if not GROUP_CHAT_ID:
        raise HTTPException(status_code=400, detail="GROUP_CHAT_ID не настроен")

    campaign = db.query(AvailabilityCampaign).order_by(
        AvailabilityCampaign.id.desc()
    ).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Нет активного опроса")

    non_voters = (await asyncio.to_thread(get_non_voters, db))["non_voters"]

    if not non_voters:
        return {"status": "all_answered", "count": 0}

    month_label = format_date(date.fromisoformat(campaign.month + "-01"), "MMMM yyyy", locale="ru_RU")

    mentions = " ".join(f"@{u}" for u in sorted(non_voters))

    poll_links = []
    for poll in campaign.polls:
        if poll.telegram_message_id:
            group_id = str(GROUP_CHAT_ID)[4:] if str(GROUP_CHAT_ID).startswith("-100") \
                else str(abs(GROUP_CHAT_ID))
            poll_links.append(f"https://t.me/c/{group_id}/{poll.telegram_message_id}")

    text = f"ребят, ещё не отметили занятость на {month_label}!\n{mentions}"
    if poll_links:
        text += "\n\n" + "\n".join(poll_links)

    await bot.send_message(chat_id=GROUP_CHAT_ID, text=text)
    return {"status": "sent", "count": len(non_voters)}


class CreateCampaignRequest(BaseModel):
    show_names: list[str]
    event_ids: list[int] | None = None
    dates: list[date] | None = None


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


@router.post("/campaign")
async def create_campaign(req: CreateCampaignRequest, db: Session = Depends(get_db)):
    """Удалить старую кампанию, создать новую, отправить опросы в Telegram."""
    from bot import bot
    from babel.dates import format_date

    if not GROUP_CHAT_ID:
        raise HTTPException(status_code=400, detail="GROUP_CHAT_ID не настроен")
    if not req.show_names:
        raise HTTPException(status_code=400, detail="Не выбраны спектакли")
    selected = _campaign_dates(req, db)

    await asyncio.to_thread(_ensure_campaign_columns, [
        (datetime.combine(d, datetime.min.time()), title) for d, _, title in selected
    ])
    old_ids = [c.id for c in db.query(AvailabilityCampaign).all()]

    month = selected[0][0].strftime("%Y-%m")
    month_label = format_date(selected[0][0], "MMMM yyyy", locale="ru_RU")

    campaign = AvailabilityCampaign(
        month=month,
        show_names=json.dumps(req.show_names, ensure_ascii=False),
    )
    db.add(campaign)
    db.flush()

    db.commit()
    # Reserve an option for actors unavailable on every date. Empty options mean retraction.
    batches = [selected[i:i+9] for i in range(0, len(selected), 9)]
    poll_suffix = f" (часть {{}}/{len(batches)})" if len(batches) > 1 else ""

    for batch_idx, batch in enumerate(batches):
        options = [_date_label(d) for d, _, _ in batch]
        question = f"Отметьте даты когда вы свободны для спектаклей — {month_label}" + (
            poll_suffix.format(batch_idx + 1) if poll_suffix else ""
        )

        try:
            message = await bot.send_poll(
                chat_id=GROUP_CHAT_ID,
                question=question,
                options=options + ["Ни одна из дат"],
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

        for i, (selected_date, event_id, _) in enumerate(batch):
            db.add(AvailabilityPollOption(
                poll_id=poll.id,
                option_index=i,
                calendar_event_id=event_id,
                selected_date=selected_date,
                date_label=_date_label(selected_date),
            ))
        db.commit()  # Preserve the mapping if sending a later poll fails.

    for old in db.query(AvailabilityCampaign).filter(AvailabilityCampaign.id.in_(old_ids)).all():
        db.delete(old)
    db.commit()
    return {"status": "sent", "month": month, "polls_count": len(batches), "events_count": len(selected)}


def _ensure_campaign_columns(events):
    if not GOOGLE_SHEETS_ID or not os.path.exists(GOOGLE_CALENDAR_JSON):
        raise HTTPException(503, "Google Sheets не настроен")
    from sheets_client import SheetsClient
    SheetsClient(GOOGLE_CALENDAR_JSON, GOOGLE_SHEETS_ID).ensure_schedule_columns(events)
