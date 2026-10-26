import logging
import os
from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/auth", tags=["auth"])
logger = logging.getLogger(__name__)


@router.get("/check")
async def check_access(request: Request):
    user = request.state.telegram_user
    return {"allowed": True, "is_admin": request.state.is_admin, "is_superadmin": request.state.is_superadmin,
            "can_finance": getattr(request.state, 'can_finance', False),
            "user_id": user.id, "username": user.username}


@router.get("/app-config")
async def app_config():
    """Вернуть публичные настройки приложения для фронтенда."""
    from config import ASSISTANT_ENABLED
    return {"assistant_enabled": ASSISTANT_ENABLED}
