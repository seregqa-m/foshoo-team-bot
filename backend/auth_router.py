import logging
import os
from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/auth", tags=["auth"])
logger = logging.getLogger(__name__)


@router.get("/check")
async def check_access(request: Request):
    user = request.state.telegram_user
    return {"allowed": True, "is_admin": request.state.is_admin, "is_superadmin": request.state.is_superadmin,
            "user_id": user.id, "username": user.username}


@router.get("/app-config")
async def app_config():
    """Вернуть публичные настройки приложения для фронтенда."""
    from config import ADMIN_ID, TROUPE_FILTER
    from core.database import SessionLocal
    from modules.notifications.models import NotificationSetting
    db = SessionLocal()
    try:
        settings = db.query(NotificationSetting).filter(
            NotificationSetting.user_id == ADMIN_ID
        ).first()
        troupe_filter = (settings.troupe_filter if settings and settings.troupe_filter else None) or TROUPE_FILTER
    finally:
        db.close()
    return {"troupe_filter": troupe_filter}
