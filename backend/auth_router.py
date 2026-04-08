import logging
import os
from fastapi import APIRouter

router = APIRouter(prefix="/api/auth", tags=["auth"])
logger = logging.getLogger(__name__)


@router.get("/check")
async def check_access(username: str = "", user_id: int = 0):
    """Проверить, есть ли пользователь в таблице труппы, и является ли он админом группы."""
    from config import GOOGLE_CALENDAR_JSON, GOOGLE_SHEETS_ID, GROUP_CHAT_ID
    from sheets_client import SheetsClient
    from bot import bot

    if not username:
        return {"allowed": False, "is_admin": False}

    # Проверяем является ли пользователь администратором Telegram-группы
    is_admin = False
    if user_id and GROUP_CHAT_ID:
        try:
            admins = await bot.get_chat_administrators(GROUP_CHAT_ID)
            is_admin = any(a.user.id == user_id for a in admins)
        except Exception as e:
            logger.warning(f"get_chat_administrators failed: {e}")

    # Если Sheets не настроен — пускаем всех
    if not GOOGLE_SHEETS_ID or not os.path.exists(GOOGLE_CALENDAR_JSON):
        return {"allowed": True, "is_admin": is_admin}

    try:
        client = SheetsClient(GOOGLE_CALENDAR_JSON, GOOGLE_SHEETS_ID)
        mapping = client.get_actor_mapping()
        allowed = username.lower().lstrip("@") in mapping
        return {"allowed": allowed, "is_admin": is_admin}
    except Exception as e:
        logger.error(f"Auth check failed: {e}")
        return {"allowed": True, "is_admin": is_admin}


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
