from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text, ForeignKey
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
    # A manual poll destination belongs to this event, not to every rehearsal.
    poll_show_id = Column(Integer, nullable=True)
    poll_show_title = Column(String, nullable=True)
    is_cancelled = Column(Boolean, default=False)
    last_synced = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CalendarColorGroup(Base):
    """Persistent visual identity; never a show, attendance source or destination."""
    __tablename__ = "calendar_color_groups"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)


class CalendarColorTitle(Base):
    __tablename__ = "calendar_color_titles"
    normalized_title = Column(String, primary_key=True)
    group_id = Column(Integer, ForeignKey('calendar_color_groups.id'), nullable=False, index=True)
