"""
Telegram bot для управления театральной студией
Показывает кнопку для открытия Mini App
"""
import logging
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo, PollAnswer
from aiogram.filters import Command
from config import BOT_TOKEN, MINI_APP_URL

logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


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


@dp.poll_answer()
async def handle_poll_answer(poll_answer: PollAnswer):
    """Сохранить ответ на Telegram-опрос в БД и записать явку в Google Sheets"""
    from core.database import SessionLocal
    from modules.polling.services import PollingService
    from modules.polling.models import Poll, PollVote
    from modules.calendar.models import CalendarEvent
    from modules.availability.models import AvailabilityPoll as AvailPoll, \
        AvailabilityPollOption, AvailabilityVote

    db = SessionLocal()
    try:
        # Проверить сначала — это опрос занятости?
        avail_poll = db.query(AvailPoll).filter(
            AvailPoll.telegram_poll_id == poll_answer.poll_id
        ).first()
        if avail_poll:
            await _handle_availability_answer(poll_answer, avail_poll, db)
            return

        answer = "retracted" if not poll_answer.option_ids else _POLL_ANSWER_MAP.get(poll_answer.option_ids[0])
        if not answer:
            logger.warning(f"Unknown poll option index: {poll_answer.option_ids[0]}")
            return

        poll = db.query(Poll).filter(Poll.telegram_poll_id == poll_answer.poll_id).first()
        if not poll:
            logger.warning(f"No DB poll for telegram_poll_id={poll_answer.poll_id}")
            return

        if answer != "retracted":
            PollingService(db).vote(poll.id, poll_answer.user.id, answer, username=poll_answer.user.username)
            logger.info(f"Poll vote saved: poll={poll.id} user={poll_answer.user.id} answer={answer}")

        # Записать явку в Google Sheets
        username = poll_answer.user.username
        if username and poll.calendar_event_id:
            # Пропускаем если у пользователя есть ответ в более новом опросе на то же событие
            has_newer_vote = db.query(PollVote).join(Poll).filter(
                Poll.calendar_event_id == poll.calendar_event_id,
                Poll.id > poll.id,
                PollVote.user_id == poll_answer.user.id,
            ).first()
            if has_newer_vote:
                logger.info(f"Sheets: skip older poll {poll.id}, user {poll_answer.user.id} has newer vote")
                return
            try:
                from config import GOOGLE_CALENDAR_JSON, GOOGLE_SHEETS_ID
                from sheets_client import SheetsClient
                import os
                if GOOGLE_SHEETS_ID and os.path.exists(GOOGLE_CALENDAR_JSON):
                    event = db.query(CalendarEvent).filter(
                        CalendarEvent.id == poll.calendar_event_id
                    ).first()
                    if event:
                        client = SheetsClient(GOOGLE_CALENDAR_JSON, GOOGLE_SHEETS_ID)
                        client.record_poll_answer(username, event.start_time, answer)
            except Exception as e:
                logger.error(f"Sheets write error: {e}")
    except Exception as e:
        logger.error(f"poll_answer handler error: {e}")
    finally:
        db.close()


async def _handle_availability_answer(poll_answer, avail_poll, db):
    """Обработать ответ на опрос занятости: записать да/нет в Google Sheets."""
    from modules.availability.models import AvailabilityPollOption, AvailabilityVote
    from modules.calendar.models import CalendarEvent

    username = poll_answer.user.username
    if not username:
        logger.warning(f"Availability poll answer from user without username: {poll_answer.user.id}")
        return

    # Зафиксировать факт голосования (upsert по user_id + poll_id)
    existing_vote = db.query(AvailabilityVote).filter(
        AvailabilityVote.poll_id == avail_poll.id,
        AvailabilityVote.user_id == poll_answer.user.id,
    ).first()
    if not existing_vote:
        db.add(AvailabilityVote(
            poll_id=avail_poll.id,
            user_id=poll_answer.user.id,
            username=username,
        ))

    # Если нет ответов (retract) — не трогаем таблицу
    if not poll_answer.option_ids:
        db.commit()
        return

    selected = set(poll_answer.option_ids)
    options = db.query(AvailabilityPollOption).filter(
        AvailabilityPollOption.poll_id == avail_poll.id
    ).all()

    try:
        from config import GOOGLE_CALENDAR_JSON, GOOGLE_SHEETS_ID
        from sheets_client import SheetsClient
        import os
        if not (GOOGLE_SHEETS_ID and os.path.exists(GOOGLE_CALENDAR_JSON)):
            db.commit()
            return
        client = SheetsClient(GOOGLE_CALENDAR_JSON, GOOGLE_SHEETS_ID)
        for opt in options:
            answer = "yes" if opt.option_index in selected else "no"
            event = db.query(CalendarEvent).filter(
                CalendarEvent.id == opt.calendar_event_id
            ).first()
            if event:
                client.record_poll_answer(username, event.start_time, answer)
    except Exception as e:
        logger.error(f"Availability sheets write error: {e}")

    db.commit()
    logger.info(f"Availability vote saved: poll={avail_poll.id} user=@{username} "
                f"selected={list(selected)}")

