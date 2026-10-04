"""Persist destinations before sending; a timeout must not silently duplicate polls."""
import asyncio
from datetime import datetime, timedelta

from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from fastapi import HTTPException

from .models import Poll
from .services import PollingService
from modules.theater.routing import event_destination, select_event_show

delivery_lock = asyncio.Lock()


async def send_publication(db, bot, poll, *, question, options, multiple=False):
    if poll.telegram_message_id:
        return
    if poll.delivery_state in ('sending', 'uncertain'):
        raise HTTPException(409, 'Telegram не подтвердил отправку. Проверьте чат перед повторным созданием опроса.')
    poll.delivery_state = 'sending'
    db.commit()
    try:
        message = await bot.send_poll(chat_id=poll.telegram_chat_id, question=question[:300],
                                      options=options, is_anonymous=False, allows_multiple_answers=multiple)
    except Exception as exc:
        poll.delivery_state = 'failed' if isinstance(exc, (TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter)) else 'uncertain'
        db.commit()
        detail = ('Telegram отклонил отправку. Проверьте права бота и повторите.' if poll.delivery_state == 'failed'
                  else 'Telegram не подтвердил отправку. Проверьте чат перед повторным созданием опроса.')
        raise HTTPException(502, detail) from exc
    poll.telegram_poll_id = message.poll.id
    poll.telegram_message_id = message.message_id
    poll.delivery_state = 'sent'
    db.commit()


async def publish_event(db, bot, event, user_id, *, automatic=False, show_id=None):
    from babel.dates import format_date
    async with delivery_lock:
        db.expire_all()
        if event.is_cancelled:
            raise HTTPException(404, 'Событие не найдено или отменено')
        if show_id is not None:
            select_event_show(db, event, show_id)
        show = event_destination(db, event)
        day = event.start_time.date()
        # Existing publications retain their original day and chat after edits.
        query = db.query(Poll).filter_by(calendar_event_id=event.id, selected_date=day,
                                        telegram_chat_id=show.telegram_chat_id)
        if not automatic:
            query = query.filter_by(is_active=True)
        poll = query.order_by(Poll.id.desc()).first()
        if poll and poll.show_id not in (None, show.id):
            poll = None
        if poll and not poll.is_active:
            return {'poll_id': poll.id, 'telegram_message_id': poll.telegram_message_id,
                    'telegram_chat_id': poll.telegram_chat_id, 'status': 'stopped'}
        dt = event.start_time
        question = f"{show.name}: кто будет {format_date(dt, 'd MMM', locale='ru_RU')} в {dt:%H:%M}?"
        if not poll:
            poll = PollingService(db).create_poll(question, user_id, calendar_event_id=event.id)
            poll.telegram_chat_id = show.telegram_chat_id
            poll.show_id = show.id
            poll.expires_at = max(datetime.utcnow() + timedelta(hours=48), datetime.combine(day + timedelta(days=1), datetime.min.time()))
            db.commit()
        await send_publication(db, bot, poll, question=question,
            options=['Буду ✅', 'Не буду ❌', 'Опоздаю ⏰', 'Не знаю 🤷'])
        return {'poll_id': poll.id, 'telegram_message_id': poll.telegram_message_id,
                'telegram_chat_id': poll.telegram_chat_id, 'status': 'sent'}
