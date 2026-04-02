"""
FastAPI router для календаря
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from core.database import get_db
from .models import CalendarEvent
from .services import CalendarService

router = APIRouter(prefix="/api/calendar", tags=["calendar"])


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
    """Синхронизировать с Google Calendar (stub для интеграции)"""
    return {"status": "sync scheduled"}
