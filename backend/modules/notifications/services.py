"""
Сервис для работы с уведомлениями
"""
import logging
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from .models import Notification, NotificationSetting, NotificationType

logger = logging.getLogger(__name__)


class NotificationService:
    """Сервис управления уведомлениями"""

    def __init__(self, db: Session):
        self.db = db

    def create_notification(
        self,
        user_id: int,
        notification_type: NotificationType,
        title: str,
        message: str,
        scheduled_at: datetime
    ) -> Notification:
        """Создать новое уведомление"""
        notification = Notification(
            user_id=user_id,
            notification_type=notification_type,
            title=title,
            message=message,
            scheduled_at=scheduled_at
        )
        self.db.add(notification)
        self.db.commit()
        logger.info(f"Created notification for user {user_id}")
        return notification

    def get_pending_notifications(self) -> list[Notification]:
        """Получить уведомления, которые нужно отправить"""
        now = datetime.utcnow()
        return self.db.query(Notification).filter(
            Notification.is_sent == False,
            Notification.scheduled_at <= now
        ).all()

    def mark_as_sent(self, notification_id: int) -> None:
        """Отметить уведомление как отправленное"""
        notification = self.db.query(Notification).filter(
            Notification.id == notification_id
        ).first()
        if notification:
            notification.is_sent = True
            notification.sent_at = datetime.utcnow()
            self.db.commit()

    def get_user_settings(self, user_id: int) -> NotificationSetting:
        """Получить настройки уведомлений пользователя"""
        settings = self.db.query(NotificationSetting).filter(
            NotificationSetting.user_id == user_id
        ).first()

        if not settings:
            settings = NotificationSetting(user_id=user_id)
            self.db.add(settings)
            self.db.commit()

        return settings

    def update_user_settings(
        self,
        user_id: int,
        poll_reminders_enabled: bool = None,
        payment_reminders_enabled: bool = None,
        event_reminders_enabled: bool = None,
        reminder_days_before: int = None,
        reminder_time: str = None,
        troupe_filter: str = None,
    ) -> NotificationSetting:
        """Обновить настройки уведомлений"""
        settings = self.get_user_settings(user_id)

        if poll_reminders_enabled is not None:
            settings.poll_reminders_enabled = poll_reminders_enabled
        if payment_reminders_enabled is not None:
            settings.payment_reminders_enabled = payment_reminders_enabled
        if event_reminders_enabled is not None:
            settings.event_reminders_enabled = event_reminders_enabled
        if reminder_days_before is not None:
            settings.reminder_days_before = reminder_days_before
        if reminder_time is not None:
            settings.reminder_time = reminder_time
        if troupe_filter is not None:
            settings.troupe_filter = troupe_filter

        self.db.commit()
        return settings
