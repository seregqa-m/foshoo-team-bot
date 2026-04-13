"""
Сервис для работы с Google Calendar
"""
import logging
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from .models import CalendarEvent
from .google_client import GoogleCalendarClient
from config import TIMEZONE

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

    @staticmethod
    def _parse_dt(dt_obj: dict) -> datetime:
        """Парсит start/end объект Google Calendar, поддерживая dateTime и всесуточные date"""
        s = dt_obj.get("dateTime") or dt_obj.get("date", "")
        if not s:
            raise ValueError(f"Empty start/end time in Google Calendar event: {dt_obj}")
        return datetime.fromisoformat(s.replace("Z", "+00:00"))

    def sync_from_google(self, events_data: list[dict], days: int = 90) -> None:
        """Синхронизировать события из Google Calendar"""
        now = datetime.utcnow()
        window_end = now + timedelta(days=days)
        synced_ids: set[str] = set()

        for event_data in events_data:
            google_event_id = event_data.get("id")
            if not google_event_id:
                continue
            synced_ids.add(google_event_id)
            try:
                start_time = self._parse_dt(event_data.get("start", {}))
                end_time = self._parse_dt(event_data.get("end", {}))
            except ValueError as e:
                logger.warning(f"Skipping event {google_event_id}: {e}")
                continue

            existing = self.db.query(CalendarEvent).filter(
                CalendarEvent.google_event_id == google_event_id
            ).first()

            if existing:
                existing.is_cancelled = False  # восстановить если было отменено
                existing.title = event_data.get("summary", "")
                existing.description = event_data.get("description", "")
                existing.location = event_data.get("location", "")
                existing.start_time = start_time
                existing.end_time = end_time
                existing.last_synced = datetime.utcnow()
            else:
                self.db.add(CalendarEvent(
                    google_event_id=google_event_id,
                    title=event_data.get("summary", ""),
                    description=event_data.get("description", ""),
                    location=event_data.get("location", ""),
                    start_time=start_time,
                    end_time=end_time,
                    last_synced=datetime.utcnow()
                ))

        # Отменить события в окне синхронизации которых нет в ответе Google
        stale = self.db.query(CalendarEvent).filter(
            CalendarEvent.is_cancelled == False,
            CalendarEvent.start_time >= now,
            CalendarEvent.start_time <= window_end,
            CalendarEvent.google_event_id.isnot(None),
            CalendarEvent.google_event_id.notin_(synced_ids),
        ).all()
        for event in stale:
            event.is_cancelled = True
            logger.info(f"Cancelled stale event: id={event.id} '{event.title}' {event.start_time.date()}")

        self.db.commit()
        logger.info(f"Synced {len(events_data)} events, cancelled {len(stale)} stale")

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
            "start": {"dateTime": start_time.isoformat(), "timeZone": TIMEZONE},
            "end": {"dateTime": end_time.isoformat(), "timeZone": TIMEZONE},
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
            "start": {"dateTime": (start_time or db_event.start_time).isoformat(), "timeZone": TIMEZONE},
            "end": {"dateTime": (end_time or db_event.end_time).isoformat(), "timeZone": TIMEZONE},
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
