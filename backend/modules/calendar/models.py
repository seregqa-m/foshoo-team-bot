from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text, ForeignKey, BigInteger, JSON
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
    is_all_day = Column(Boolean, default=False)
    google_html_link = Column(Text, nullable=True)
    recurring_event_id = Column(String, nullable=True)
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


class CalendarSubscription(Base):
    """Shared feed with a one-time, immutable selection of catalog show IDs."""
    __tablename__ = 'calendar_shared_subscriptions'
    id = Column(Integer, primary_key=True)
    scope_key = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)
    show_ids = Column(JSON, nullable=False)
    token = Column(String, unique=True, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    revoked_at = Column(DateTime, nullable=True)


class CalendarWatchState(Base):
    """Key 0 is the baseline marker; other keys are calendar event IDs."""
    __tablename__ = 'calendar_watch_state'
    event_id = Column(Integer, primary_key=True, autoincrement=False)
    title = Column(Text, nullable=False)
    issue_key = Column(String, nullable=True)


class CalendarWatchDelivery(Base):
    __tablename__ = 'calendar_watch_deliveries'
    issue_key = Column(String, primary_key=True)
    recipient_id = Column(BigInteger, primary_key=True)
    sent_at = Column(DateTime, nullable=True)
    retry_after = Column(DateTime, nullable=True)
