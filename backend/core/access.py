"""Telegram identity verification and server-side API permissions."""
import asyncio
import hashlib
import hmac
import json
import logging
import os
import time
from dataclasses import dataclass
from collections import OrderedDict
from urllib.parse import parse_qsl

from fastapi import HTTPException, Request
from config import BOT_TOKEN, GROUP_CHAT_ID, GOOGLE_CALENDAR_JSON, GOOGLE_SHEETS_ID

INIT_DATA_TTL = 86400
TELEGRAM_ACCESS_TIMEOUT = 4
SHEETS_ACCESS_TIMEOUT = 6
logger = logging.getLogger(__name__)


async def _access_step(stage, operation, timeout):
    started = time.monotonic()
    outcome = "ok"
    try:
        return await asyncio.wait_for(operation, timeout=timeout)
    except asyncio.TimeoutError:
        outcome = "timeout"
        raise HTTPException(503, "Проверка доступа временно недоступна. Попробуй ещё раз.") from None
    except Exception as exc:
        outcome = type(exc).__name__
        raise
    finally:
        elapsed = time.monotonic() - started
        log = logger.warning if outcome != "ok" or elapsed >= 1 else logger.debug
        log("Access check stage=%s outcome=%s duration=%.3fs", stage, outcome, elapsed)


@dataclass(frozen=True)
class TelegramUser:
    id: int
    username: str = ""
    display_name: str = ""


def verify_init_data(raw: str, *, bot_token: str = BOT_TOKEN, now=None) -> TelegramUser:
    reason = "missing" if not raw else "malformed"
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
            reason = "signature"
            raise ValueError("signature")
        age = (time.time() if now is None else now) - int(data["auth_date"])
        if not -30 <= age <= INIT_DATA_TTL:
            reason = "expired"
            raise ValueError("expired")
        user = json.loads(data["user"])
        if type(user["id"]) is not int or user["id"] <= 0:
            raise ValueError("user")
        return TelegramUser(user["id"], str(user.get("username") or ""),
                            " ".join(str(user.get(k) or "").strip() for k in ("first_name", "last_name")).strip())
    except (ValueError, KeyError, TypeError):
        logger.warning("Telegram initData rejected reason=%s", reason)
        raise HTTPException(401, "Открой приложение заново через Telegram") from None


async def is_super_admin(user_id: int) -> bool:
    from modules.admin.services import has_superadmin_role
    return await asyncio.to_thread(has_superadmin_role, user_id)


async def is_admin(user_id: int) -> bool:
    return await is_super_admin(user_id) or await _is_group_admin(user_id)


async def _is_group_admin(user_id: int) -> bool:
    if not GROUP_CHAT_ID:
        return False
    from bot import bot
    try:
        member = await _access_step(
            "telegram", bot.get_chat_member(GROUP_CHAT_ID, user_id),
            TELEGRAM_ACCESS_TIMEOUT,
        )
        return member.status in ("creator", "administrator")
    except HTTPException:
        raise
    except Exception:
        # Do not cache an API failure as a successful non-admin check.
        raise HTTPException(503, "Проверка доступа временно недоступна") from None


def _known_actor(username: str) -> bool:
    if not username:
        return False
    if not GOOGLE_SHEETS_ID or not os.path.exists(GOOGLE_CALENDAR_JSON):
        raise HTTPException(503, "Проверка доступа временно недоступна")
    from sheets_client import SheetsClient
    try:
        mapping = SheetsClient(GOOGLE_CALENDAR_JSON, GOOGLE_SHEETS_ID, timeout=3).get_actor_mapping()
        return username.lower().lstrip("@") in mapping
    except Exception:
        raise HTTPException(503, "Проверка доступа временно недоступна") from None


_access_cache = OrderedDict()


async def _permissions(user):
    # Never cache global privileges: revocation must affect the next request.
    if await is_super_admin(user.id):
        return True, True, True
    key = (user.id, user.username)
    # Cache operations contain no awaits; network calls never hold a global lock.
    cached = _access_cache.get(key)
    if cached and cached[0] > time.monotonic():
        return (*cached[1:], False)
    admin = await _is_group_admin(user.id)
    allowed = admin or await _access_step(
        "sheets", asyncio.to_thread(_known_actor, user.username), SHEETS_ACCESS_TIMEOUT,
    )
    # Failed/timed-out checks never reach the cache.
    _access_cache[key] = (time.monotonic() + 60, allowed, admin)
    _access_cache.move_to_end(key)
    while len(_access_cache) > 512:
        _access_cache.popitem(last=False)
    return allowed, admin, False


async def authorize_api(request: Request):
    """Applied to every /api router; identity fields cannot override Telegram."""
    user = verify_init_data(request.headers.get("X-Telegram-Init-Data", ""))
    if request.url.path.rstrip('/') == '/api/auth/check':
        from modules.admin.services import remember_identity
        await asyncio.to_thread(remember_identity, user)
    allowed, admin, superadmin = await _permissions(user)
    if not allowed:
        raise HTTPException(403, "Приложение доступно только участникам труппы")
    supplied_sources = [dict(request.query_params)]
    if request.headers.get("content-type", "").startswith("application/json"):
        try:
            raw_body = await request.body()
            body = json.loads(raw_body) if raw_body else None
            if isinstance(body, dict):
                supplied_sources.append(body)
        except ValueError:
            raise HTTPException(400, "Некорректный JSON") from None
    for supplied in supplied_sources:
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
    request.state.is_superadmin = superadmin
    return user
