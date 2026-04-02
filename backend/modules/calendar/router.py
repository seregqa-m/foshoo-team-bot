"""
FastAPI router для календаря
"""
import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from datetime import datetime
from sqlalchemy.orm import Session
from core.database import get_db
from config import GOOGLE_CALENDAR_ID, GOOGLE_CALENDAR_JSON
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
