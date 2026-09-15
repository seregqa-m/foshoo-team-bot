from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text
from core.database import Base
from core.time import CalendarDateTime
from datetime import datetime


class CalendarEvent(Base):
    """Модель события репетиции из Google Calendar"""
    __tablename__ = "calendar_events"

    id = Column(Integer, primary_key=True, index=True)
    google_event_id = Column(String, unique=True, index=True)
    title = Column(String, index=True)
    description = Column(Text, nullable=True)
    start_time = Column(CalendarDateTime, index=True)
    end_time = Column(CalendarDateTime)
    location = Column(String, nullable=True)
    is_cancelled = Column(Boolean, default=False)
    last_synced = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
