"""
Сервис для работы с Google Calendar
"""
import logging
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from .models import CalendarEvent

logger = logging.getLogger(__name__)


class CalendarService:
    """Сервис управления календарем"""

    def __init__(self, db: Session):
        self.db = db

    def get_upcoming_events(self, days: int = 30) -> list[CalendarEvent]:
        """Получить предстоящие события"""
        now = datetime.utcnow()
        future = now + timedelta(days=days)

        return self.db.query(CalendarEvent).filter(
            CalendarEvent.start_time >= now,
            CalendarEvent.start_time <= future,
            CalendarEvent.is_cancelled == False
        ).order_by(CalendarEvent.start_time).all()

    def get_event_by_id(self, event_id: int) -> CalendarEvent:
        """Получить событие по ID"""
        return self.db.query(CalendarEvent).filter(
            CalendarEvent.id == event_id
        ).first()

    def get_next_event(self) -> CalendarEvent:
        """Получить следующее событие"""
        now = datetime.utcnow()
        return self.db.query(CalendarEvent).filter(
            CalendarEvent.start_time > now,
            CalendarEvent.is_cancelled == False
        ).order_by(CalendarEvent.start_time).first()

    def sync_from_google(self, events_data: list[dict]) -> None:
        """Синхронизировать события из Google Calendar"""
        for event_data in events_data:
            google_event_id = event_data.get("id")
            existing = self.db.query(CalendarEvent).filter(
                CalendarEvent.google_event_id == google_event_id
            ).first()

            if existing:
                existing.title = event_data.get("summary", "")
                existing.description = event_data.get("description", "")
                existing.location = event_data.get("location", "")
                existing.start_time = datetime.fromisoformat(
                    event_data.get("start", {}).get("dateTime", "").replace("Z", "+00:00")
                )
                existing.end_time = datetime.fromisoformat(
                    event_data.get("end", {}).get("dateTime", "").replace("Z", "+00:00")
                )
                existing.last_synced = datetime.utcnow()
            else:
                new_event = CalendarEvent(
                    google_event_id=google_event_id,
                    title=event_data.get("summary", ""),
                    description=event_data.get("description", ""),
                    location=event_data.get("location", ""),
                    start_time=datetime.fromisoformat(
                        event_data.get("start", {}).get("dateTime", "").replace("Z", "+00:00")
                    ),
                    end_time=datetime.fromisoformat(
                        event_data.get("end", {}).get("dateTime", "").replace("Z", "+00:00")
                    ),
                    last_synced=datetime.utcnow()
                )
                self.db.add(new_event)

        self.db.commit()
        logger.info(f"Synced {len(events_data)} events from Google Calendar")
