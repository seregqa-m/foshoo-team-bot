"""
FastAPI router для календаря
"""
import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from datetime import datetime
from sqlalchemy.orm import Session
from core.database import get_db
from config import GOOGLE_CALENDAR_ID, GOOGLE_CALENDAR_JSON
from .models import CalendarEvent
from .services import CalendarService
from .google_client import GoogleCalendarClient
from .classification import classify_event
from modules.theater.routing import saved_event_show, ShowSelectionRequired
from modules.theater.models import TheaterShow, TheaterChat
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


class LaunchPollRequest(BaseModel):
    show_id: int = Field(strict=True, gt=0)


def get_google_client():
    """Получить Google Calendar клиент если доступен"""
    if os.path.exists(GOOGLE_CALENDAR_JSON) and GOOGLE_CALENDAR_ID:
        try:
            return GoogleCalendarClient(GOOGLE_CALENDAR_JSON)
        except Exception as e:
            logger.warning(f"Google Calendar client unavailable: {e}")
    return None


@router.get("/meta")
def get_calendar_meta():
    """Вернуть ссылку на Google Calendar."""
    url = None
    if GOOGLE_CALENDAR_ID:
        from urllib.parse import quote
        url = f"https://calendar.google.com/calendar/r?cid={quote(GOOGLE_CALENDAR_ID)}"
    return {"calendar_url": url}


@router.get("/events")
def get_events(days: int = 30, db: Session = Depends(get_db), include_past: bool = False):
    """Получить события; include_past добавляет сохранённую историю."""
    service = CalendarService(db)
    events = service.get_upcoming_events(days, include_past=include_past)
    return {
        "events": [
            {
                "id": e.id,
                "title": e.title,
                **classify_event(e.title),
                "poll_show_name": show.name if (show := saved_event_show(db, e)) else None,
                "description": e.description,
                "start_time": e.start_time.isoformat(),
                "end_time": e.end_time.isoformat(),
                "location": e.location,
            }
            for e in events
        ]
    }


@router.get("/events/next")
def get_next_event(db: Session = Depends(get_db)):
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
def sync_calendar(db: Session = Depends(get_db)):
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
def create_event(
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
def update_event(
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
    db: Session = Depends(get_db),
    request: LaunchPollRequest | None = None,
):
    """Создать опрос о посещаемости для события и отправить его в Telegram-группу"""
    from bot import bot
    from modules.polling.delivery import publish_event
    if not user_id:
        raise HTTPException(400, 'user_id required')
    event = CalendarService(db).get_event_by_id(event_id)
    if not event or event.is_cancelled:
        raise HTTPException(404, 'Событие не найдено или отменено')
    try:
        return await publish_event(db, bot, event, user_id,
                                   show_id=request.show_id if request else None)
    except ShowSelectionRequired as exc:
        chats = {chat.telegram_chat_id: chat.title for chat in db.query(TheaterChat).all()}
        raise HTTPException(409, {
            'code': 'show_required',
            'message': exc.detail,
            'shows': [{'id': show.id, 'name': show.name,
                       'telegram_chat_id': show.telegram_chat_id,
                       'chat_title': chats.get(show.telegram_chat_id)}
                      for show in db.query(TheaterShow).order_by(TheaterShow.name).all()],
        }) from exc


@router.delete("/events/{event_id}")
def delete_event(
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
