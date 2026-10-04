import asyncio
import json
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from modules.admin.models import AdminSetup, SuperAdmin
from modules.admin.services import BOOTSTRAP_KEY
from .models import TheaterAudit, TheaterChat, TheaterShow, TheaterShowAlias


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
    try:
        chat = await asyncio.wait_for(bot.get_chat(chat_id), timeout=5)
        member = await asyncio.wait_for(bot.get_chat_member(chat_id, bot.id), timeout=5)
    except Exception:
        raise HTTPException(502, 'Не удалось проверить чат в Telegram. Проверьте ID и доступ бота.') from None
    if chat.type not in ('group', 'supergroup') or chat.id != chat_id:
        raise HTTPException(400, 'Нужен ID группы или супергруппы Telegram')
    if member.status != 'administrator' or not member.can_pin_messages:
        raise HTTPException(400, 'Назначьте бота администратором чата с правом закреплять сообщения')
    return chat.title or str(chat.id)


def register_chat(db, actor_id, chat_id, title):
    try:
        lock_management(db, actor_id)
        chat = db.get(TheaterChat, chat_id, populate_existing=True)
        if chat is None:
            chat = TheaterChat(telegram_chat_id=chat_id, title=title)
            db.add(chat)
            audit(db, actor_id, 'chat_registered', chat_id=chat_id, title=title)
        chat.title = title
        chat.checked_at = datetime.utcnow()
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


def set_show(db, actor_id, show_id, name, chat_id, expected_revision):
    try:
        lock_management(db, actor_id)
        show = db.get(TheaterShow, show_id, populate_existing=True)
        if show is None:
            raise HTTPException(404, 'Спектакль не найден')
        if show.revision != expected_revision:
            raise HTTPException(409, 'Настройки изменил другой администратор. Обновите список.')
        if chat_id is not None and db.get(TheaterChat, chat_id) is None:
            raise HTTPException(404, 'Сначала зарегистрируйте и проверьте чат')
        name = ' '.join(name.split())
        if not name or len(name) > 200:
            raise HTTPException(422, 'Название спектакля должно содержать от 1 до 200 символов')
        normalized = normalize_name(name)
        alias = db.get(TheaterShowAlias, normalized)
        if alias is not None and alias.show_id != show.id:
            raise HTTPException(409, 'Это название уже связано с другим спектаклем')
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
