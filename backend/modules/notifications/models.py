from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text, Enum as SQLEnum
from core.database import Base
from datetime import datetime
import enum


class NotificationType(str, enum.Enum):
    """Типы уведомлений"""
    POLL_REMINDER = "poll_reminder"
    PAYMENT_REMINDER = "payment_reminder"
    EVENT_REMINDER = "event_reminder"
    CUSTOM = "custom"


class Notification(Base):
    """Модель уведомления/напоминания"""
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True)  # Telegram user ID
    notification_type = Column(SQLEnum(NotificationType), index=True)
    title = Column(String)
    message = Column(Text)
    scheduled_at = Column(DateTime, index=True)
    is_sent = Column(Boolean, default=False)
    sent_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class NotificationSetting(Base):
    """Модель настроек уведомлений пользователя"""
    __tablename__ = "notification_settings"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, unique=True, index=True)
    poll_reminders_enabled = Column(Boolean, default=True)
    payment_reminders_enabled = Column(Boolean, default=True)
    event_reminders_enabled = Column(Boolean, default=True)
    reminder_hours_before = Column(Integer, default=24)  # за сколько часов до события
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
