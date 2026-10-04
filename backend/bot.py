"""
Telegram bot для управления театральной студией
Показывает кнопку для открытия Mini App
"""
from __future__ import annotations
import asyncio
from core.time import local_now
import logging
from aiogram import Bot, Dispatcher, F
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    WebAppInfo, PollAnswer,
)
from aiogram.filters import Command
from config import BOT_TOKEN, MINI_APP_URL, TELEGRAM_PROXY_URL, GROUP_CHAT_ID, MODERATION_CHANNEL, MODERATION_ADMIN_ID, MODERATION_AUTO_DELETE
from modules.moderation.services import ModerationService

logger = logging.getLogger(__name__)

bot = Bot(
    token=BOT_TOKEN,
    session=AiohttpSession(timeout=15, proxy=TELEGRAM_PROXY_URL),
)
dp = Dispatcher()
moderation = ModerationService(MODERATION_CHANNEL, MODERATION_ADMIN_ID, GROUP_CHAT_ID, auto_delete=MODERATION_AUTO_DELETE)


@dp.message.outer_middleware()
async def moderate_discussion(handler, event, data):
    if await moderation.inspect(event, data['bot'], data['event_update'].update_id):
        return
    return await handler(event, data)


@dp.edited_message()
async def moderate_edited_comment(message: Message, event_update):
    await moderation.inspect(message, bot, event_update.update_id)


@dp.callback_query(F.data.startswith('mod:'))
async def on_moderation_action(callback: CallbackQuery):
    await moderation.callback(callback, bot)


@dp.message(F.chat.type == 'private', F.forward_origin)
async def on_forwarded_for_moderation(message: Message, event_update):
    await moderation.manual_check(message, bot, event_update.update_id)


@dp.message(Command('moderation'))
async def moderation_status(message: Message):
    if message.chat.type != 'private' or message.from_user.id != MODERATION_ADMIN_ID:
        return
    await moderation.resolve(bot, force=True)
    await message.answer(moderation.status)


@dp.message(Command("start"))
async def cmd_start(message: Message):
    """Обработчик команды /start"""
    logger.info(f"User {message.from_user.id} started bot")

    if message.chat.type == "private":
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text="🎭 Открыть приложение",
                web_app=WebAppInfo(url=MINI_APP_URL)
            )
        ]])
        await message.answer(
            "Привет! 👋\n\n"
            "Нажми кнопку ниже, чтобы открыть приложение управления театральной студией.",
            reply_markup=kb
        )
    else:
        await message.answer(
            "🎭 Чтобы открыть приложение — нажми кнопку меню бота рядом с полем ввода, "
            "или открой бота в личных сообщениях."
        )


@dp.message(Command("help"))
async def cmd_help(message: Message):
    """Обработчик команды /help"""
    await message.answer(
        "📖 Справка\n\n"
        "Доступные команды:\n"
        "/start — главное меню и кнопка приложения\n"
        "/help — эта справка\n\n"
        "Нажми на кнопку 'Открыть приложение' чтобы начать работу!"
    )


# 0=Буду, 1=Не буду, 2=Опоздаю (→ да), 3=Не знаю (→ не писать в таблицу)
_POLL_ANSWER_MAP = {0: "yes", 1: "no", 2: "yes", 3: "unknown"}


_vote_lock = asyncio.Lock()


@dp.poll_answer()
async def handle_poll_answer(poll_answer: PollAnswer, event_update=None):
    async with _vote_lock:
        await asyncio.to_thread(_process_poll_answer, poll_answer,
                                event_update.update_id if event_update else None)


def _process_poll_answer(poll_answer: PollAnswer, update_id=None):
    """Persist the publication vote and the shared person/day answer atomically."""
    from core.database import SessionLocal
    from modules.polling.services import PollingService
    from modules.polling.models import Poll
    from modules.availability.models import AvailabilityPoll
    from modules.attendance.services import answer_lock, accept_update, export_pending

    if not poll_answer.user:
        return  # anonymous chat votes cannot identify an actor
    with SessionLocal() as db:
        try:
            with answer_lock:
                if not accept_update(db, update_id):
                    return
                availability = db.query(AvailabilityPoll).filter_by(telegram_poll_id=poll_answer.poll_id).first()
                if availability:
                    _handle_availability_answer(poll_answer, availability, db, export=False)
                else:
                    poll = db.query(Poll).filter_by(telegram_poll_id=poll_answer.poll_id).first()
                    if not poll or not poll.is_active:
                        return
                    answer = 'retracted' if not poll_answer.option_ids else (
                        _POLL_ANSWER_MAP.get(poll_answer.option_ids[0]) if len(poll_answer.option_ids) == 1 else None)
                    if answer is None:
                        return
                    PollingService(db).vote(poll.id, poll_answer.user.id, answer, poll_answer.user.username)
            export_pending(db)
        except Exception:
            db.rollback()
            logger.exception('poll_answer handler error')


# ──────────────── Availability intent detection ──────────────── #

_MONTH_MAP: dict[str, tuple[int, str]] = {
    "январ": (1, "январе"),   "феврал": (2, "феврале"),
    "март":  (3, "марте"),    "апрел":  (4, "апреле"),
    "мая":   (5, "мае"),      "май":    (5, "мае"),
    "июн":   (6, "июне"),     "июл":    (7, "июле"),
    "август": (8, "августе"), "сентябр": (9, "сентябре"),
    "октябр": (10, "октябре"), "ноябр": (11, "ноябре"),
    "декабр": (12, "декабре"),
}

_AVAILABILITY_TRIGGERS = ["проголосу", "опрос", "занятост", "свободн", "спектакл"]


def _detect_availability_intent(text: str) -> tuple[int, int, str] | None:
    """Возвращает (year, month_num, month_label) или None."""
    from datetime import datetime
    low = text.lower()
    if not any(t in low for t in _AVAILABILITY_TRIGGERS):
        return None
    now = local_now()
    for key, (month_num, label) in _MONTH_MAP.items():
        if key in low:
            year = now.year if month_num >= now.month else now.year + 1
            return (year, month_num, label)
    return None


async def _llm_confirm_intent(text: str, month_label: str) -> bool:
    try:
        from modules.assistant.llm_client import get_llm_client, ChatMessage as LLMMsg
        llm = get_llm_client()
        resp = await llm.chat([
            LLMMsg(role="system", text="Ты определяешь намерение. Отвечай строго: да или нет."),
            LLMMsg(role="user", text=(
                f"Пользователь написал в чате театральной студии: «{text}»\n\n"
                f"Человек предлагает провести опрос занятости на {month_label}? да/нет"
            )),
        ])
        return "да" in (resp.text or "").lower()
    except Exception as e:
        logger.warning(f"LLM intent check failed: {e}")
        return True  # если LLM недоступна — доверяем keyword match


@dp.message(F.chat.type.in_({"group", "supergroup"}))
async def handle_group_message(message: Message):
    if not await asyncio.to_thread(_chat_shows, message.chat.id):
        return
    if not message.text:
        return
    intent = _detect_availability_intent(message.text)
    if not intent:
        return
    year, month_num, month_label = intent
    if not await _llm_confirm_intent(message.text, month_label):
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="✅ Запустить опрос",
            callback_data=f"avail_start_{year}_{month_num}",
        ),
        InlineKeyboardButton(text="❌ Не надо", callback_data="avail_cancel"),
    ]])
    await message.reply(f"Запустить опрос занятости на {month_label}?", reply_markup=kb)


def _chat_shows(chat_id):
    from core.database import SessionLocal
    from modules.theater.models import TheaterShow
    with SessionLocal() as db:
        return [s.name for s in db.query(TheaterShow).filter_by(telegram_chat_id=chat_id)]


def _prepare_campaign(year, month_num, chat_id=None):
    import calendar
    from datetime import datetime
    from core.database import SessionLocal
    from modules.calendar.models import CalendarEvent
    from modules.theater.models import TheaterShow
    from modules.theater.routing import show_aliases
    from modules.calendar.classification import is_troupe_event
    from modules.notifications.models import NotificationSetting
    from modules.availability.router import CreateCampaignRequest
    from config import ADMIN_ID, TROUPE_FILTER
    first = datetime(year, month_num, 1)
    last = datetime(year, month_num, calendar.monthrange(year, month_num)[1], 23, 59, 59)
    with SessionLocal() as db:
        query = db.query(TheaterShow)
        if chat_id is not None:
            query = query.filter_by(telegram_chat_id=chat_id)
        shows = [s.name for s in query.all()]
        settings = db.query(NotificationSetting).filter_by(user_id=ADMIN_ID).first()
        troupe = ((settings.troupe_filter if settings else None) or TROUPE_FILTER).lower()
        aliases = list(show_aliases(db))
        events = db.query(CalendarEvent).filter(
            CalendarEvent.start_time >= first, CalendarEvent.start_time <= last,
            CalendarEvent.is_cancelled == False,
        ).order_by(CalendarEvent.start_time).all()
        return CreateCampaignRequest(show_names=shows,
            event_ids=[e.id for e in events if is_troupe_event(e.title, aliases, troupe)])


async def _launch_campaign_for_month(year: int, month_num: int, chat_id: int) -> dict:
    from core.database import SessionLocal
    from modules.availability.router import create_campaign
    req = await asyncio.to_thread(_prepare_campaign, year, month_num, chat_id)
    with SessionLocal() as db:
        result = await create_campaign(req, db)
    return {'ok': result['status'] == 'sent', 'error': '; '.join(e['error'] for e in result.get('errors', [])), **result}


@dp.callback_query(F.data.startswith("avail_start_"))
async def on_avail_start(callback: CallbackQuery):
    from core.access import is_super_admin
    chat_id = callback.message.chat.id
    configured = await asyncio.to_thread(_chat_shows, chat_id)
    allowed = bool(configured) and await is_super_admin(callback.from_user.id)
    if configured and not allowed:
        try:
            member = await bot.get_chat_member(chat_id, callback.from_user.id)
            allowed = member.status in ('creator', 'administrator')
        except Exception:
            allowed = False
    if not allowed:
        await callback.answer("Доступно только администратору группы", show_alert=True)
        return
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)

    parts = callback.data.split("_")  # ["avail", "start", "2026", "8"]
    year, month_num = int(parts[2]), int(parts[3])

    try:
        result = await _launch_campaign_for_month(year, month_num, chat_id)
        if result["ok"]:
            await callback.message.reply(
                f"✅ Опрос занятости запущен: {result['polls_count']} опрос(а) "
                f"на {result['events_count']} дат"
            )
        else:
            await callback.message.reply(f"⚠️ {result['error']}")
    except Exception as e:
        logger.error(f"avail_start callback error: {e}", exc_info=True)
        await callback.message.reply("❌ Не удалось запустить опрос. Попробуй через приложение.")


@dp.callback_query(F.data == "avail_cancel")
async def on_avail_cancel(callback: CallbackQuery):
    await callback.answer("Отменено")
    await callback.message.edit_reply_markup(reply_markup=None)


def _handle_availability_answer(poll_answer, avail_poll, db, *, export=True):
    import json
    from datetime import datetime
    from modules.availability.models import AvailabilityVote
    from modules.attendance.services import answer_lock, record_answers, option_day, export_pending

    with answer_lock:
        selected = set(poll_answer.option_ids)
        options = avail_poll.options
        valid = {o.option_index for o in options}
        # Telegram permits combining "none" with dates. Treat it as no dates only
        # when selected alone; explicit selected dates otherwise take precedence.
        if not selected.issubset(valid | {len(options)}):
            return
        existing = db.query(AvailabilityVote).filter_by(poll_id=avail_poll.id, user_id=poll_answer.user.id).first()
        username = poll_answer.user.username or (existing.username if existing else None)
        if not selected:
            if existing:
                db.delete(existing)
        else:
            if not existing:
                existing = AvailabilityVote(poll_id=avail_poll.id, user_id=poll_answer.user.id)
                db.add(existing)
            existing.username = username
            existing.option_ids = json.dumps(sorted(selected))
            existing.voted_at = datetime.utcnow()
        answers = {day: ('yes' if opt.option_index in selected else 'no') if selected else 'retracted'
                   for opt in options if (day := option_day(opt, db))}
        record_answers(db, poll_answer.user.id, username, f'availability:{avail_poll.id}', answers)
        db.commit()
    if export:
        export_pending(db)
