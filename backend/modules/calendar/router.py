"""
FastAPI router для календаря
"""
import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from datetime import datetime
from sqlalchemy.orm import Session
from core.database import get_db
from config import GOOGLE_CALENDAR_ID, GOOGLE_CALENDAR_JSON, GROUP_CHAT_ID
from .models import CalendarEvent
from .services import CalendarService
from .google_client import GoogleCalendarClient
import os

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/calendar", tags=["calendar"])


class CreateEventRequest(BaseModel):
    title: str
    start_time: str  # ISO format
    end_time: str    # ISO format
    location: str = None
    description: str = None


class UpdateEventRequest(BaseModel):
    title: str = None
    start_time: str = None
    end_time: str = None
    location: str = None
    description: str = None


def get_google_client():
    """Получить Google Calendar клиент если доступен"""
    if os.path.exists(GOOGLE_CALENDAR_JSON) and GOOGLE_CALENDAR_ID:
        try:
            return GoogleCalendarClient(GOOGLE_CALENDAR_JSON)
        except Exception as e:
            logger.warning(f"Google Calendar client unavailable: {e}")
    return None


@router.get("/events")
async def get_events(days: int = 30, db: Session = Depends(get_db)):
    """Получить предстоящие события"""
    service = CalendarService(db)
    events = service.get_upcoming_events(days)
    return {
        "events": [
            {
                "id": e.id,
                "title": e.title,
                "description": e.description,
                "start_time": e.start_time.isoformat(),
                "end_time": e.end_time.isoformat(),
                "location": e.location,
            }
            for e in events
        ]
    }


@router.get("/events/next")
async def get_next_event(db: Session = Depends(get_db)):
    """Получить следующее событие"""
    service = CalendarService(db)
    event = service.get_next_event()

    if not event:
        return {"event": None}

    return {
        "event": {
            "id": event.id,
            "title": event.title,
            "description": event.description,
            "start_time": event.start_time.isoformat(),
            "end_time": event.end_time.isoformat(),
            "location": event.location,
        }
    }


@router.post("/sync")
async def sync_calendar(db: Session = Depends(get_db)):
    """Синхронизировать с Google Calendar"""
    google_client = get_google_client()
    if not google_client:
        raise HTTPException(
            status_code=400,
            detail="Google Calendar not configured"
        )

    try:
        events_data = google_client.get_events(GOOGLE_CALENDAR_ID)
        service = CalendarService(db, google_client)
        service.sync_from_google(events_data)
        return {
            "status": "synced",
            "count": len(events_data)
        }
    except Exception as e:
        logger.error(f"Sync failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/events")
async def create_event(
    request: CreateEventRequest,
    db: Session = Depends(get_db)
):
    """Создать новое событие"""
    google_client = get_google_client()
    if not google_client:
        raise HTTPException(
            status_code=400,
            detail="Google Calendar not configured"
        )

    try:
        start = datetime.fromisoformat(request.start_time)
        end = datetime.fromisoformat(request.end_time)

        service = CalendarService(db, google_client)
        event = service.create_event(
            calendar_id=GOOGLE_CALENDAR_ID,
            title=request.title,
            start_time=start,
            end_time=end,
            location=request.location,
            description=request.description
        )
        return event
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid datetime format: {e}")
    except Exception as e:
        logger.error(f"Failed to create event: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/events/{event_id}")
async def update_event(
    event_id: int,
    request: UpdateEventRequest,
    db: Session = Depends(get_db)
):
    """Обновить событие"""
    google_client = get_google_client()
    if not google_client:
        raise HTTPException(
            status_code=400,
            detail="Google Calendar not configured"
        )

    try:
        start = None
        end = None
        if request.start_time:
            start = datetime.fromisoformat(request.start_time)
        if request.end_time:
            end = datetime.fromisoformat(request.end_time)

        service = CalendarService(db, google_client)
        event = service.update_event(
            calendar_id=GOOGLE_CALENDAR_ID,
            event_id=event_id,
            title=request.title,
            start_time=start,
            end_time=end,
            location=request.location,
            description=request.description
        )
        return event
    except ValueError as e:
        if "not found" in str(e):
            raise HTTPException(status_code=404, detail=str(e))
        raise HTTPException(status_code=400, detail=f"Invalid datetime format: {e}")
    except Exception as e:
        logger.error(f"Failed to update event: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/events/{event_id}/poll")
async def launch_poll_for_event(
    event_id: int,
    user_id: int = None,
    db: Session = Depends(get_db)
):
    """Создать опрос о посещаемости для события и отправить его в Telegram-группу"""
    from bot import bot
    from modules.polling.services import PollingService

    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required")
    if not GROUP_CHAT_ID:
        raise HTTPException(
            status_code=400,
            detail="GROUP_CHAT_ID не настроен. Добавьте бота в группу и укажите GROUP_CHAT_ID в .env"
        )

    cal_service = CalendarService(db)
    event = cal_service.get_event_by_id(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    poll_service = PollingService(db)
    poll = poll_service.create_poll(
        title=f"кто будет на занятии: {event.title}",
        created_by=user_id,
        expires_in_hours=48,
        calendar_event_id=event_id,
    )

    MONTHS_RU = ['янв','фев','мар','апр','май','июн','июл','авг','сен','окт','ноя','дек']
    dt = event.start_time
    date_str = f"{dt.day} {MONTHS_RU[dt.month - 1]} в {dt.strftime('%H:%M')}"

    try:
        message = await bot.send_poll(
            chat_id=GROUP_CHAT_ID,
            question=f"Кто будет {date_str}?\n{event.title}",
            options=["Буду ✅", "Не буду ❌", "Опоздаю ⏰", "Не знаю 🤷"],
            is_anonymous=False,
            allows_multiple_answers=False,
        )
        poll_service.save_telegram_ids(poll.id, message.poll.id, message.message_id)
    except Exception as e:
        logger.error(f"Failed to send Telegram poll: {e}")
        raise HTTPException(
            status_code=502,
            detail=f"Опрос сохранён в БД (id={poll.id}), но отправка в Telegram не удалась: {e}"
        )

    return {"poll_id": poll.id, "telegram_message_id": message.message_id, "status": "sent"}


@router.delete("/events/{event_id}")
async def delete_event(
    event_id: int,
    db: Session = Depends(get_db)
):
    """Удалить событие"""
    google_client = get_google_client()
    if not google_client:
        raise HTTPException(
            status_code=400,
            detail="Google Calendar not configured"
        )

    try:
        service = CalendarService(db, google_client)
        service.delete_event(GOOGLE_CALENDAR_ID, event_id)
        return {"status": "deleted"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to delete event: {e}")
        raise HTTPException(status_code=500, detail=str(e))
