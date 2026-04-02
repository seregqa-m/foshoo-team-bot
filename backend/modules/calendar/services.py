"""
Сервис для работы с Google Calendar
"""
import logging
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from .models import CalendarEvent
from .google_client import GoogleCalendarClient

logger = logging.getLogger(__name__)


class CalendarService:
    """Сервис управления календарем"""

    def __init__(self, db: Session, google_client: GoogleCalendarClient = None):
        self.db = db
        self.google_client = google_client

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

    def create_event(
        self,
        calendar_id: str,
        title: str,
        start_time: datetime,
        end_time: datetime,
        location: str = None,
        description: str = None
    ) -> dict:
        """Создать событие в Google Calendar и БД"""
        if not self.google_client:
            raise ValueError("Google client not available")

        event_data = {
            "summary": title,
            "start": {"dateTime": start_time.isoformat()},
            "end": {"dateTime": end_time.isoformat()},
        }
        if location:
            event_data["location"] = location
        if description:
            event_data["description"] = description

        google_event = self.google_client.create_event(calendar_id, event_data)

        db_event = CalendarEvent(
            google_event_id=google_event["id"],
            title=title,
            description=description,
            location=location,
            start_time=start_time,
            end_time=end_time,
            last_synced=datetime.utcnow()
        )
        self.db.add(db_event)
        self.db.commit()
        self.db.refresh(db_event)

        logger.info(f"Created event: {db_event.id}")
        return {
            "id": db_event.id,
            "title": db_event.title,
            "google_event_id": db_event.google_event_id,
            "start_time": db_event.start_time.isoformat(),
            "end_time": db_event.end_time.isoformat(),
        }

    def update_event(
        self,
        calendar_id: str,
        event_id: int,
        title: str = None,
        start_time: datetime = None,
        end_time: datetime = None,
        location: str = None,
        description: str = None
    ) -> dict:
        """Обновить событие в Google Calendar и БД"""
        if not self.google_client:
            raise ValueError("Google client not available")

        db_event = self.get_event_by_id(event_id)
        if not db_event:
            raise ValueError(f"Event {event_id} not found")

        # Подготовить данные для Google
        event_data = {
            "summary": title or db_event.title,
            "start": {"dateTime": (start_time or db_event.start_time).isoformat()},
            "end": {"dateTime": (end_time or db_event.end_time).isoformat()},
        }
        if location is not None:
            event_data["location"] = location
        if description is not None:
            event_data["description"] = description

        self.google_client.update_event(calendar_id, db_event.google_event_id, event_data)

        # Обновить БД
        if title:
            db_event.title = title
        if start_time:
            db_event.start_time = start_time
        if end_time:
            db_event.end_time = end_time
        if location is not None:
            db_event.location = location
        if description is not None:
            db_event.description = description
        db_event.last_synced = datetime.utcnow()

        self.db.commit()
        self.db.refresh(db_event)

        logger.info(f"Updated event: {event_id}")
        return {
            "id": db_event.id,
            "title": db_event.title,
            "google_event_id": db_event.google_event_id,
            "start_time": db_event.start_time.isoformat(),
            "end_time": db_event.end_time.isoformat(),
        }

    def delete_event(self, calendar_id: str, event_id: int) -> None:
        """Удалить событие из Google Calendar и БД"""
        if not self.google_client:
            raise ValueError("Google client not available")

        db_event = self.get_event_by_id(event_id)
        if not db_event:
            raise ValueError(f"Event {event_id} not found")

        self.google_client.delete_event(calendar_id, db_event.google_event_id)

        # Пометить как отменённое в БД (мягкое удаление)
        db_event.is_cancelled = True
        self.db.commit()

        logger.info(f"Deleted event: {event_id}")
