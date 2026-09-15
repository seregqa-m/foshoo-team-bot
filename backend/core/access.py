"""Telegram identity verification and server-side API permissions."""
import asyncio
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl

from fastapi import HTTPException, Request
from config import BOT_TOKEN, ADMIN_ID, GROUP_CHAT_ID, GOOGLE_CALENDAR_JSON, GOOGLE_SHEETS_ID

INIT_DATA_TTL = 86400


@dataclass(frozen=True)
class TelegramUser:
    id: int
    username: str = ""


def verify_init_data(raw: str, *, bot_token: str = BOT_TOKEN, now=None) -> TelegramUser:
    try:
        pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True)
        data = dict(pairs)
        if len(data) != len(pairs):
            raise ValueError("duplicate fields")
        signature = data.pop("hash")
        check = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
        secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("signature")
        age = (time.time() if now is None else now) - int(data["auth_date"])
        if not -30 <= age <= INIT_DATA_TTL:
            raise ValueError("expired")
        user = json.loads(data["user"])
        if type(user["id"]) is not int or user["id"] <= 0:
            raise ValueError("user")
        return TelegramUser(user["id"], str(user.get("username") or ""))
    except (ValueError, KeyError, TypeError):
        raise HTTPException(401, "Открой приложение заново через Telegram") from None


async def is_admin(user_id: int) -> bool:
    if ADMIN_ID and user_id == ADMIN_ID:
        return True
    if not GROUP_CHAT_ID:
        return False
    from bot import bot
    try:
        member = await bot.get_chat_member(GROUP_CHAT_ID, user_id)
        return member.status in ("creator", "administrator")
    except Exception:
        # An unavailable Telegram API must not grant administrative access.
        return False


def _known_actor(username: str) -> bool:
    if not username:
        return False
    if not GOOGLE_SHEETS_ID or not os.path.exists(GOOGLE_CALENDAR_JSON):
        raise HTTPException(503, "Проверка доступа временно недоступна")
    from sheets_client import SheetsClient
    try:
        mapping = SheetsClient(GOOGLE_CALENDAR_JSON, GOOGLE_SHEETS_ID).get_actor_mapping()
        return username.lower().lstrip("@") in mapping
    except Exception:
        raise HTTPException(503, "Проверка доступа временно недоступна") from None


async def authorize_api(request: Request):
    """Applied to every /api router; identity fields cannot override Telegram."""
    user = verify_init_data(request.headers.get("X-Telegram-Init-Data", ""))
    admin = await is_admin(user.id)
    if not admin and not await asyncio.to_thread(_known_actor, user.username):
        raise HTTPException(403, "Приложение доступно только участникам труппы")
    supplied = dict(request.query_params)
    if request.headers.get("content-type", "").startswith("application/json"):
        try:
            body = await request.json()
            if isinstance(body, dict):
                supplied.update(body)
        except ValueError:
            raise HTTPException(400, "Некорректный JSON") from None
    if "user_id" in supplied and str(supplied["user_id"]) != str(user.id):
        raise HTTPException(403, "Нельзя действовать от имени другого пользователя")
    if "username" in supplied and str(supplied["username"]).lower().lstrip("@") != user.username.lower():
        raise HTTPException(403, "Пользователь не совпадает с данными Telegram")
    path = request.url.path.rstrip("/")
    member_writes = {
        "/api/finance/expense", "/api/finance/income",
        "/api/assistant/chat", "/api/assistant/execute",
    }
    voting = path.startswith("/api/polls/") and path.endswith("/vote")
    if request.method not in ("GET", "HEAD", "OPTIONS") and path not in member_writes and not voting and not admin:
        raise HTTPException(403, "Это действие доступно только администратору")
    request.state.telegram_user = user
    request.state.is_admin = admin
    return user
