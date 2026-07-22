"""
Telegram bot для управления театральной студией
Показывает кнопку для открытия Mini App
"""
import logging
from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    WebAppInfo, PollAnswer,
)
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
    now = datetime.utcnow()
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


def _date_label(dt) -> str:
    from babel.dates import format_date
    return f"{format_date(dt, 'EE', locale='ru_RU').rstrip('.')} {format_date(dt, 'd MMM', locale='ru_RU')}"


async def _launch_campaign_for_month(year: int, month_num: int) -> dict:
    """Создать кампанию занятости, отправить опросы в группу. Возвращает результат."""
    import calendar as cal_mod
    import json
    import os
    from datetime import datetime
    from babel.dates import format_date
    from core.database import SessionLocal
    from modules.calendar.models import CalendarEvent
    from modules.availability.models import (
        AvailabilityCampaign, AvailabilityPoll, AvailabilityPollOption,
    )
    from modules.notifications.models import NotificationSetting
    from config import (
        ADMIN_ID, GROUP_CHAT_ID, GOOGLE_CALENDAR_JSON, GOOGLE_SHEETS_ID, TROUPE_FILTER,
    )

    if not GROUP_CHAT_ID:
        return {"ok": False, "error": "GROUP_CHAT_ID не настроен"}

    first_day = datetime(year, month_num, 1)
    last_day = datetime(year, month_num, cal_mod.monthrange(year, month_num)[1], 23, 59, 59)
    month_label = format_date(first_day, "MMMM yyyy", locale="ru_RU")

    db = SessionLocal()
    try:
        settings = db.query(NotificationSetting).filter(
            NotificationSetting.user_id == ADMIN_ID
        ).first()
        troupe_filter = (
            settings.troupe_filter if settings and settings.troupe_filter else TROUPE_FILTER
        ).lower()

        show_names_lower: list[str] = []
        show_names: list[str] = []
        if GOOGLE_SHEETS_ID and os.path.exists(GOOGLE_CALENDAR_JSON):
            try:
                from sheets_client import SheetsClient
                sc = SheetsClient(GOOGLE_CALENDAR_JSON, GOOGLE_SHEETS_ID)
                all_shows = sc.get_show_names() or []
                show_names_lower = [s.lower() for s in all_shows]
                show_names = ([settings.current_show] if settings and settings.current_show
                              else all_shows)
                sc.ensure_schedule_columns([
                    (e.start_time, e.title)
                    for e in db.query(CalendarEvent).filter(
                        CalendarEvent.start_time >= first_day,
                        CalendarEvent.start_time <= last_day,
                        CalendarEvent.is_cancelled == False,  # noqa: E712
                    ).all()
                ])
            except Exception as e:
                logger.warning(f"Sheets prep failed: {e}")

        events = (
            db.query(CalendarEvent)
            .filter(
                CalendarEvent.start_time >= first_day,
                CalendarEvent.start_time <= last_day,
                CalendarEvent.is_cancelled == False,  # noqa: E712
            )
            .order_by(CalendarEvent.start_time)
            .all()
        )
        filtered = [
            e for e in events
            if troupe_filter in e.title.lower()
            and not any(s in e.title.lower() for s in show_names_lower)
        ]

        if not filtered:
            return {"ok": False, "error": f"Нет событий для труппы в {month_label}"}
        if len(filtered) > 20:
            return {"ok": False, "error": "Слишком много дат (максимум 20)"}

        # Удалить старую кампанию
        old = db.query(AvailabilityCampaign).order_by(AvailabilityCampaign.id.desc()).first()
        if old:
            db.delete(old)
            db.flush()

        campaign = AvailabilityCampaign(
            month=first_day.strftime("%Y-%m"),
            show_names=json.dumps(show_names, ensure_ascii=False),
        )
        db.add(campaign)
        db.flush()

        batches = [filtered[i:i + 10] for i in range(0, len(filtered), 10)]
        suffix = f" (часть {{}}/{len(batches)})" if len(batches) > 1 else ""

        for idx, batch in enumerate(batches):
            question = f"Отметьте даты когда вы свободны для спектаклей — {month_label}" + (
                suffix.format(idx + 1) if suffix else ""
            )
            msg = await bot.send_poll(
                chat_id=GROUP_CHAT_ID,
                question=question,
                options=[_date_label(e.start_time) for e in batch],
                is_anonymous=False,
                allows_multiple_answers=True,
            )
            poll = AvailabilityPoll(
                campaign_id=campaign.id,
                telegram_poll_id=msg.poll.id,
                telegram_message_id=msg.message_id,
            )
            db.add(poll)
            db.flush()
            for i, event in enumerate(batch):
                db.add(AvailabilityPollOption(
                    poll_id=poll.id,
                    option_index=i,
                    calendar_event_id=event.id,
                    date_label=_date_label(event.start_time),
                ))

        db.commit()
        return {"ok": True, "polls_count": len(batches), "events_count": len(filtered)}

    except Exception as e:
        db.rollback()
        raise
    finally:
        db.close()


@dp.callback_query(F.data.startswith("avail_start_"))
async def on_avail_start(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)

    parts = callback.data.split("_")  # ["avail", "start", "2026", "8"]
    year, month_num = int(parts[2]), int(parts[3])

    try:
        result = await _launch_campaign_for_month(year, month_num)
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

