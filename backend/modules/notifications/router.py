"""
FastAPI router для уведомлений
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from core.database import get_db
from .services import NotificationService


class UpdateSettingsRequest(BaseModel):
    poll_reminders_enabled: bool = None
    payment_reminders_enabled: bool = None
    event_reminders_enabled: bool = None
    reminder_days_before: int = None
    reminder_time: str = None
    troupe_filter: str = None


router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("/settings")
async def get_notification_settings(
    user_id: int = None,
    db: Session = Depends(get_db)
):
    """Получить настройки уведомлений"""
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required")

    service = NotificationService(db)
    settings = service.get_user_settings(user_id)

    return {
        "poll_reminders_enabled": settings.poll_reminders_enabled,
        "payment_reminders_enabled": settings.payment_reminders_enabled,
        "event_reminders_enabled": settings.event_reminders_enabled,
        "reminder_days_before": settings.reminder_days_before,
        "reminder_time": settings.reminder_time,
        "troupe_filter": settings.troupe_filter or "труппа 1",
    }


@router.post("/settings")
async def update_notification_settings(
    request: UpdateSettingsRequest,
    user_id: int = None,
    db: Session = Depends(get_db)
):
    """Обновить настройки уведомлений"""
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required")

    service = NotificationService(db)
    service.update_user_settings(
        user_id,
        poll_reminders_enabled=request.poll_reminders_enabled,
        payment_reminders_enabled=request.payment_reminders_enabled,
        event_reminders_enabled=request.event_reminders_enabled,
        reminder_days_before=request.reminder_days_before,
        reminder_time=request.reminder_time,
        troupe_filter=request.troupe_filter,
    )

    return {"status": "updated"}
