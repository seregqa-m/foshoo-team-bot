import asyncio
import json
import logging
from datetime import datetime

from aiogram.exceptions import (ClientDecodeError, TelegramBadRequest, TelegramForbiddenError,
                                TelegramMigrateToChat, TelegramNetworkError, TelegramNotFound,
                                TelegramRetryAfter, TelegramServerError, TelegramUnauthorizedError)
from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from modules.admin.models import AdminSetup, SuperAdmin
from modules.admin.services import BOOTSTRAP_KEY
from .models import TheaterAudit, TheaterChat, TheaterShow, TheaterShowAlias

logger = logging.getLogger(__name__)
CHAT_INSPECTION_TIMEOUT = 15


def normalize_name(value):
    return ' '.join(value.split()).casefold()


def lock_management(db, actor_id):
    """Serialize changes with global role revocations and recheck the caller."""
    changed = db.execute(update(AdminSetup).where(AdminSetup.key == BOOTSTRAP_KEY)
                         .values(revision=AdminSetup.revision + 1)).rowcount
    if not changed:
        raise HTTPException(503, 'Первый суперадминистратор ещё не настроен')
    if not db.get(SuperAdmin, actor_id, populate_existing=True):
        raise HTTPException(403, 'Управление доступно только суперадминистратору')


def audit(db, actor_id, action, **details):
    db.add(TheaterAudit(actor_id=actor_id, action=action,
                       details=json.dumps(details, ensure_ascii=False)))


async def inspect_chat(bot, chat_id):
    """Read-only verification; never send a test message to a real chat."""
    stage = 'getChat'
    try:
        chat = await asyncio.wait_for(bot.get_chat(chat_id), timeout=CHAT_INSPECTION_TIMEOUT)
        if chat.type not in ('group', 'supergroup') or chat.id != chat_id:
            raise HTTPException(400, 'Нужен ID группы или супергруппы Telegram. Получите его командой /chatid в нужной группе.')
        stage = 'getChatMember'
        member = await asyncio.wait_for(bot.get_chat_member(chat_id, bot.id), timeout=CHAT_INSPECTION_TIMEOUT)
    except HTTPException:
        raise
    except Exception as exc:
        # Exception strings can include token-bearing URLs and complete Telegram
        # responses. Log only identifiers, exception type and a fixed category.
        category = type(exc).__name__
        status = 502
        if isinstance(exc, TelegramMigrateToChat):
            status = 400
            detail = f'У этой группы изменился ID после преобразования в супергруппу. Введите новый ID: {exc.migrate_to_chat_id}.'
        elif isinstance(exc, (asyncio.TimeoutError, TelegramNetworkError, TelegramServerError)):
            status = 504 if isinstance(exc, asyncio.TimeoutError) else 502
            detail = 'Сервер бота не получил ответ Telegram. Это не результат проверки прав. Повторите сохранение; если ошибка повторяется, проверьте соединение сервера с Telegram и прокси.'
        elif isinstance(exc, TelegramRetryAfter):
            status = 429
            detail = f'Telegram временно ограничил запросы. Повторите сохранение через {exc.retry_after} сек.'
        elif isinstance(exc, TelegramUnauthorizedError):
            detail = 'Telegram отклонил авторизацию бота. Нужно проверить BOT_TOKEN на сервере.'
        elif isinstance(exc, TelegramForbiddenError):
            status = 400
            detail = f'Telegram отказал боту (ID {bot.id}) в доступе к чату {chat_id}. Проверьте, что администратором добавлен именно бот этого приложения. Точный ID группы можно получить командой /chatid.'
        elif isinstance(exc, (TelegramBadRequest, TelegramNotFound)):
            status = 400
            if 'chat not found' in exc.message.lower():
                category = 'chat_not_found'
                detail = f'Telegram не нашёл чат {chat_id} для этого бота. Отправьте /chatid в нужную группу и скопируйте полученный ID полностью.'
            else:
                detail = f'Telegram отклонил проверку чата {chat_id} на шаге {stage}. Получите ID командой /chatid в группе; если ID совпадает, передайте код ошибки: {category}/{stage}.'
        elif isinstance(exc, ClientDecodeError):
            detail = 'Бот не смог разобрать ответ Telegram. ID и права могут быть корректными; требуется проверка совместимости библиотеки Telegram на сервере (ClientDecodeError).'
        else:
            detail = f'Проверка чата не завершилась из-за внутренней ошибки ({category}/{stage}). Это не подтверждает проблему с ID или правами.'
        logger.warning('Telegram chat inspection failed chat_id=%s bot_id=%s stage=%s reason=%s',
                       chat_id, bot.id, stage, category)
        raise HTTPException(status, detail) from None
    if member.status != 'administrator' or not getattr(member, 'can_pin_messages', False):
        raise HTTPException(400, 'Назначьте бота администратором чата с правом закреплять сообщения')
    return chat.title or str(chat.id)


def _remember_chat(db, actor_id, chat_id, title):
    chat = db.get(TheaterChat, chat_id, populate_existing=True)
    if chat is None:
        chat = TheaterChat(telegram_chat_id=chat_id, title=title)
        db.add(chat)
        audit(db, actor_id, 'chat_registered', chat_id=chat_id, title=title)
    chat.title = title
    chat.checked_at = datetime.utcnow()
    return chat


def register_chat(db, actor_id, chat_id, title):
    try:
        lock_management(db, actor_id)
        chat = _remember_chat(db, actor_id, chat_id, title)
        db.commit()
        return chat
    except Exception:
        db.rollback()
        raise


def import_shows(db, actor_id, names):
    """Add missing names only. Never overwrite an existing name or route."""
    cleaned = {}
    for value in names:
        name = ' '.join(value.split())
        if not name or len(name) > 200:
            raise HTTPException(422, 'Название спектакля должно содержать от 1 до 200 символов')
        cleaned.setdefault(normalize_name(name), name)
    try:
        lock_management(db, actor_id)
        existing = {row.normalized_name for row in db.query(TheaterShow).all()}
        existing.update(row.normalized_name for row in db.query(TheaterShowAlias).all())
        added = [name for key, name in cleaned.items() if key not in existing]
        for name in added:
            show = TheaterShow(name=name, normalized_name=normalize_name(name))
            db.add(show)
            db.flush()
            db.add(TheaterShowAlias(normalized_name=show.normalized_name, show_id=show.id))
        if added:
            audit(db, actor_id, 'shows_added', names=added)
        db.commit()
        return len(added)
    except Exception:
        db.rollback()
        raise


def set_show(db, actor_id, show_id, name, chat_id, expected_revision, verified_chat_title=None):
    try:
        lock_management(db, actor_id)
        show = db.get(TheaterShow, show_id, populate_existing=True)
        if show is None:
            raise HTTPException(404, 'Спектакль не найден')
        if show.revision != expected_revision:
            raise HTTPException(409, 'Настройки изменил другой администратор. Обновите список.')
        if chat_id is not None and verified_chat_title is None and db.get(TheaterChat, chat_id) is None:
            raise HTTPException(404, 'Сначала зарегистрируйте и проверьте чат')
        name = ' '.join(name.split())
        if not name or len(name) > 200:
            raise HTTPException(422, 'Название спектакля должно содержать от 1 до 200 символов')
        normalized = normalize_name(name)
        alias = db.get(TheaterShowAlias, normalized)
        if alias is not None and alias.show_id != show.id:
            raise HTTPException(409, 'Это название уже связано с другим спектаклем')
        if chat_id is not None and verified_chat_title is not None:
            _remember_chat(db, actor_id, chat_id, verified_chat_title)
            db.flush()
        if show.name != name or show.telegram_chat_id != chat_id:
            audit(db, actor_id, 'show_updated', show_id=show.id,
                  old_name=show.name, name=name, old_chat_id=show.telegram_chat_id, chat_id=chat_id)
            for key in {show.normalized_name, normalized}:
                if db.get(TheaterShowAlias, key) is None:
                    db.add(TheaterShowAlias(normalized_name=key, show_id=show.id))
            show.name, show.normalized_name = name, normalized
            show.telegram_chat_id = chat_id
            show.revision += 1
        db.commit()
        return show
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, 'Спектакль с таким названием уже существует') from None
    except Exception:
        db.rollback()
        raise
