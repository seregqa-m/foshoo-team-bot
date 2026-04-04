import logging
import os
from fastapi import APIRouter

router = APIRouter(prefix="/api/auth", tags=["auth"])
logger = logging.getLogger(__name__)


@router.get("/check")
async def check_access(username: str = ""):
    """Проверить, есть ли пользователь в таблице труппы."""
    from config import GOOGLE_CALENDAR_JSON, GOOGLE_SHEETS_ID
    from sheets_client import SheetsClient

    if not username:
        return {"allowed": False}

    # Если Sheets не настроен — пускаем всех (чтобы не ломать дев-окружение)
    if not GOOGLE_SHEETS_ID or not os.path.exists(GOOGLE_CALENDAR_JSON):
        return {"allowed": True}

    from config import ADMIN_ID, ADMIN_USERNAME
    uname = username.lower().lstrip("@")
    is_admin = uname == ADMIN_USERNAME.lower().lstrip("@")

    try:
        client = SheetsClient(GOOGLE_CALENDAR_JSON, GOOGLE_SHEETS_ID)
        mapping = client.get_actor_mapping()
        allowed = uname in mapping
        return {"allowed": allowed, "is_admin": is_admin}
    except Exception as e:
        logger.error(f"Auth check failed: {e}")
        return {"allowed": True, "is_admin": is_admin}
