"""
Главная точка входа приложения
Запускает FastAPI сервер и Telegram бота
"""
import asyncio
import logging
import sys
import os
from fastapi import FastAPI, Depends
from core.access import authorize_api
from core.time import local_now
from fastapi.middleware.cors import CORSMiddleware
from core.database import init_db, SessionLocal, engine
from config import LOG_LEVEL, API_HOST, API_PORT, GOOGLE_CALENDAR_JSON, GOOGLE_CALENDAR_ID, SYNC_INTERVAL_MINUTES
from modules.calendar.router import router as calendar_router
from modules.calendar.services import CalendarService
from modules.calendar.google_client import GoogleCalendarClient
from modules.polling.router import router as polling_router
from modules.notifications.router import router as notifications_router
from modules.availability.router import router as availability_router
from modules.planning.router import router as planning_router
from modules.assistant.router import router as assistant_router
from auth_router import router as auth_router
from sheets_router import router as sheets_router
from finance_router import router as finance_router
from links_router import router as links_router
from afisha_router import router as afisha_router
from bot import bot, dp

# Логирование
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

# FastAPI приложение
app = FastAPI(
    title="Theater Studio Bot API",
    description="API для управления театральной студией",
    version="0.1.0"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)



def run_migrations():
    """Добавить новые колонки если их нет (идемпотентно)"""
    from sqlalchemy import text, inspect
    with engine.begin() as conn:
        for stmt in [
            "ALTER TABLE polls ADD COLUMN telegram_poll_id TEXT",
            "ALTER TABLE polls ADD COLUMN telegram_message_id INTEGER",
            "ALTER TABLE polls ADD COLUMN reminder_sent_at DATETIME",
            "ALTER TABLE poll_votes ADD COLUMN username TEXT",
            "ALTER TABLE notification_settings ADD COLUMN reminder_days_before INTEGER DEFAULT 3",
            "ALTER TABLE notification_settings ADD COLUMN reminder_time TEXT DEFAULT '18:00'",
            "ALTER TABLE notification_settings ADD COLUMN troupe_filter TEXT DEFAULT 'труппа 1'",
            "ALTER TABLE notification_settings ADD COLUMN current_show TEXT",
            "ALTER TABLE availability_poll_options ADD COLUMN selected_date DATE",
        ]:
            table, column = stmt.split()[2], stmt.split()[5]
            if column not in {c["name"] for c in inspect(conn).get_columns(table)}:
                conn.execute(text(stmt))


async def _run_bot():
    """Запустить Telegram бота в режиме polling с авторестартом"""
    delay = 5
    while True:
        started = asyncio.get_running_loop().time()
        try:
            await bot.delete_webhook(drop_pending_updates=False)
            logger.info("⏱ Bot: starting polling...")
            await dp.start_polling(bot, handle_signals=False, close_bot_session=False)
        except Exception as e:
            logger.error(f"❌ Bot polling stopped: {e}")
        if asyncio.get_running_loop().time() - started >= 60:
            delay = 5
        logger.info(f"⏱ Bot: restarting in {delay}s...")
        await asyncio.sleep(delay)
        delay = min(delay * 2, 60)


@dp.startup()
async def _on_bot_ready():
    logger.info("✅ Bot polling active")


# Background sync task для Google Calendar
def _ensure_schedule_columns(db) -> None:
    """Создать недостающие столбцы в «График [составы]» для спектаклей тек. и след. месяца."""
    from datetime import date, datetime as dt_cls, timedelta
    import calendar as cal_mod
    from config import GOOGLE_SHEETS_ID
    from modules.calendar.models import CalendarEvent

    if not (GOOGLE_SHEETS_ID and os.path.exists(GOOGLE_CALENDAR_JSON)):
        return

    today = local_now().date()
    range_start = dt_cls(today.year, today.month, 1)
    next_month = today.month % 12 + 1
    next_month_year = today.year + (1 if today.month == 12 else 0)
    last_day = cal_mod.monthrange(next_month_year, next_month)[1]
    range_end = dt_cls(next_month_year, next_month, last_day, 23, 59, 59)

    events = (
        db.query(CalendarEvent)
        .filter(
            CalendarEvent.start_time >= range_start,
            CalendarEvent.start_time <= range_end,
            CalendarEvent.is_cancelled == False,  # noqa: E712
        )
        .order_by(CalendarEvent.start_time)
        .all()
    )
    if not events:
        return

    try:
        from config import ADMIN_ID, TROUPE_FILTER
        from modules.notifications.models import NotificationSetting
        from sheets_client import SheetsClient

        setting = db.query(NotificationSetting).filter(
            NotificationSetting.user_id == ADMIN_ID
        ).first()
        troupe_filter = (setting.troupe_filter if setting and setting.troupe_filter else TROUPE_FILTER).lower()

        sc = SheetsClient(GOOGLE_CALENDAR_JSON, GOOGLE_SHEETS_ID)
        show_names_lower = {s.lower() for s in (sc.get_show_names() or [])}

        matched_events = [
            (e.start_time, e.title)
            for e in events
            if troupe_filter in e.title.lower()
            or any(s in e.title.lower() for s in show_names_lower)
        ]
        if matched_events:
            added = sc.ensure_schedule_columns(matched_events)
            if added:
                logger.info(f"✅ Schedule columns: добавлено {added} новых столбцов")
    except Exception as e:
        logger.error(f"❌ ensure_schedule_columns failed: {e}")


def sync_calendar_once():
    if not (os.path.exists(GOOGLE_CALENDAR_JSON) and GOOGLE_CALENDAR_ID):
        return
    google_client = GoogleCalendarClient(GOOGLE_CALENDAR_JSON)
    events = google_client.get_events(GOOGLE_CALENDAR_ID)
    with SessionLocal() as db:
        CalendarService(db, google_client).sync_from_google(events)
        _ensure_schedule_columns(db)
    logger.info("Calendar sync completed: %s events", len(events))


def sync_finance_once():
    from finance_router import sync_finance_from_sheets
    with SessionLocal() as db:
        return sync_finance_from_sheets(db)


async def _sync_loop(job, initial_delay):
    await asyncio.sleep(initial_delay)
    while True:
        try:
            await asyncio.to_thread(job)
        except Exception:
            logger.exception("Background sync failed: %s", job.__name__)
        await asyncio.sleep(SYNC_INTERVAL_MINUTES * 60)


async def sync_calendar_background():
    await _sync_loop(sync_calendar_once, 10)


async def sync_finance_background():
    await _sync_loop(sync_finance_once, 30)


def _show_names():
    from config import GOOGLE_SHEETS_ID
    from sheets_client import SheetsClient
    if not (GOOGLE_SHEETS_ID and os.path.exists(GOOGLE_CALENDAR_JSON)):
        return []
    return [s.lower() for s in SheetsClient(GOOGLE_CALENDAR_JSON, GOOGLE_SHEETS_ID).get_show_names()]


def _reminder_usernames(current_show):
    from config import GOOGLE_SHEETS_ID
    from sheets_client import SheetsClient
    if not (GOOGLE_SHEETS_ID and os.path.exists(GOOGLE_CALENDAR_JSON)):
        raise RuntimeError("Google Sheets is not configured")
    client = SheetsClient(GOOGLE_CALENDAR_JSON, GOOGLE_SHEETS_ID)
    mapping = client.get_actor_mapping()
    if not current_show:
        return set(mapping)
    cast = {n.lower() for n in client.get_show_cast(current_show)}
    return {uname for uname, name in mapping.items() if name.lower() in cast}


async def poll_reminder_background():
    """Проверять каждую минуту: нужно ли отправить напоминание об опросе в группу."""
    await asyncio.sleep(15)

    while True:
        try:
            await _cleanup_old_polls()
        except Exception as e:
            logger.error(f"❌ Poll cleanup failed: {e}")
        try:
            await _auto_create_polls()
        except Exception as e:
            logger.error(f"❌ Auto poll creation failed: {e}")
        try:
            await _send_poll_reminders()
        except Exception as e:
            logger.error(f"❌ Reminder check failed: {e}")
        await asyncio.sleep(60)


async def _cleanup_old_polls():
    """Удалить опросы у которых событие закончилось вчера или раньше."""
    from datetime import datetime, timedelta
    from modules.polling.models import Poll, PollVote
    from modules.calendar.models import CalendarEvent

    cutoff = local_now() - timedelta(days=1)
    db = SessionLocal()
    try:
        old_polls = db.query(Poll).join(
            CalendarEvent, Poll.calendar_event_id == CalendarEvent.id
        ).filter(CalendarEvent.end_time < cutoff).all()

        for poll in old_polls:
            db.query(PollVote).filter(PollVote.poll_id == poll.id).delete()
            db.delete(poll)
        if old_polls:
            db.commit()
            logger.info(f"🗑 Cleaned up {len(old_polls)} old poll(s)")
    finally:
        db.close()


async def _auto_create_polls():
    """Автоматически создать опрос в группе за N дней до события."""
    from datetime import datetime, timedelta
    from modules.polling.models import Poll
    from modules.polling.services import PollingService
    from modules.notifications.models import NotificationSetting
    from modules.calendar.models import CalendarEvent
    from config import ADMIN_ID, GROUP_CHAT_ID, GOOGLE_CALENDAR_JSON, GOOGLE_SHEETS_ID
    import os

    if not GROUP_CHAT_ID:
        return

    now = local_now()
    db = SessionLocal()
    try:
        settings = db.query(NotificationSetting).filter(
            NotificationSetting.user_id == ADMIN_ID
        ).first()
        if not (settings and settings.poll_reminders_enabled):
            return

        moscow_now = now
        h, m = map(int, settings.reminder_time.split(":"))
        if (moscow_now.hour, moscow_now.minute) < (h, m):
            return

        target_date = (now + timedelta(days=settings.reminder_days_before)).date()

        show_names_lower = await asyncio.to_thread(_show_names)

        for event in db.query(CalendarEvent).filter(CalendarEvent.is_cancelled == False).all():
            if event.start_time.date() != target_date:
                continue
            if show_names_lower and any(s in event.title.lower() for s in show_names_lower):
                continue
            from config import TROUPE_FILTER
            if (settings.troupe_filter or TROUPE_FILTER).lower() not in event.title.lower():
                continue
            existing = db.query(Poll).filter(
                Poll.calendar_event_id == event.id,
                Poll.is_active == True,
            ).first()
            if existing and existing.telegram_message_id:
                continue  # уже отправлен в Telegram

            from babel.dates import format_date
            dt = event.start_time
            date_str = f"в {format_date(dt, 'EEEE', locale='ru_RU')} {format_date(dt, 'd MMM', locale='ru_RU')} в {dt.strftime('%H:%M')}"

            poll_service = PollingService(db)
            poll = existing or poll_service.create_poll(
                title=f"Кто будет {date_str}?",
                created_by=ADMIN_ID,
                expires_in_hours=settings.reminder_days_before * 24 + 48,
                calendar_event_id=event.id,
            )
            try:
                message = await bot.send_poll(
                    chat_id=GROUP_CHAT_ID,
                    question=f"Кто будет {date_str}?",
                    options=["Буду ✅", "Не буду ❌", "Опоздаю ⏰", "Не знаю 🤷"],
                    is_anonymous=False,
                    allows_multiple_answers=False,
                )
                poll_service.save_telegram_ids(poll.id, message.poll.id, message.message_id)
                logger.info(f"✅ Auto poll created: '{event.title}' on {target_date} → poll {poll.id}")
            except Exception as e:
                logger.error(f"❌ Auto poll send failed for event {event.id}: {e}")
    finally:
        db.close()


async def _send_poll_reminders():
    """Отправить напоминание об опросе за 1 день до события и закрепить опрос."""
    from datetime import datetime, timedelta
    from modules.polling.models import Poll, PollVote
    from modules.notifications.models import NotificationSetting
    from config import ADMIN_ID, GROUP_CHAT_ID, GOOGLE_CALENDAR_JSON, GOOGLE_SHEETS_ID
    import os

    if not GROUP_CHAT_ID:
        return

    now = local_now()
    db = SessionLocal()
    try:
        settings = db.query(NotificationSetting).filter(
            NotificationSetting.user_id == ADMIN_ID
        ).first()
        reminder_time_str = settings.reminder_time if settings else "18:00"
        if not (settings and settings.poll_reminders_enabled):
            return

        moscow_now = now
        h, m = map(int, reminder_time_str.split(":"))
        if (moscow_now.hour, moscow_now.minute) < (h, m):
            return

        target_date = (now + timedelta(days=1)).date()  # всегда за 1 день

        from modules.calendar.models import CalendarEvent
        polls = db.query(Poll).join(
            CalendarEvent, Poll.calendar_event_id == CalendarEvent.id
        ).filter(
            Poll.is_active == True,
            Poll.reminder_sent_at == None,
        ).all()

        show_names_lower = await asyncio.to_thread(_show_names)
        target_usernames = await asyncio.to_thread(_reminder_usernames, settings.current_show)

        for poll in polls:
            event = db.query(CalendarEvent).filter(CalendarEvent.id == poll.calendar_event_id).first()
            if not event or event.is_cancelled or not poll.telegram_message_id or event.start_time.date() != target_date:
                continue
            if show_names_lower and any(s in event.title.lower() for s in show_names_lower):
                continue

            voted_usernames = {
                v.username.lower() for v in
                db.query(PollVote).filter(
                    PollVote.poll_id == poll.id,
                    PollVote.answer.in_(["yes", "no"]),
                    PollVote.username != None,
                ).all()
                if v.username
            }

            unvoted_mentions = [f"@{name}" for name in sorted(target_usernames - voted_usernames)]

            if not unvoted_mentions:
                poll.reminder_sent_at = datetime.utcnow()
                db.commit()
                continue

            date_str = event.start_time.strftime("%d.%m в %H:%M")
            mentions = " ".join(unvoted_mentions)
            poll_link = ""
            if poll.telegram_message_id and GROUP_CHAT_ID:
                group_id = str(GROUP_CHAT_ID)[4:] if str(GROUP_CHAT_ID).startswith("-100") else str(abs(GROUP_CHAT_ID))
                poll_link = f"\n\nhttps://t.me/c/{group_id}/{poll.telegram_message_id}"

            await bot.send_message(chat_id=GROUP_CHAT_ID,
                                   text=f"ребят, отметьте присутствие {date_str}!\n{mentions}{poll_link}")

            if poll.telegram_message_id:
                try:
                    await bot.pin_chat_message(chat_id=GROUP_CHAT_ID,
                                               message_id=poll.telegram_message_id,
                                               disable_notification=True)
                except Exception as e:
                    logger.warning(f"Pin poll failed: {e}")

            poll.reminder_sent_at = datetime.utcnow()
            db.commit()
            logger.info(f"✅ Reminder sent for poll {poll.id}, event {event.start_time.date()}")

    finally:
        db.close()


# Инициализировать БД
@app.on_event("startup")
async def startup():
    logger.info("🚀 Starting application")
    import modules.availability.models  # noqa: ensure tables created
    import modules.planning.models  # noqa: durable calendar/schedule operations
    import modules.assistant.models  # noqa: ensure assistant_action_log table created
    logger.info("⏱ Running migrations...")
    init_db()
    run_migrations()
    logger.info("✅ Database initialized")

    app.state.tasks = []
    # Запустить Telegram бота
    app.state.tasks.append(asyncio.create_task(_run_bot()))
    logger.info("⏱ Bot task scheduled")

    # Запустить background sync task для Google Calendar
    app.state.tasks.append(asyncio.create_task(sync_calendar_background()))
    logger.info("⏱ Calendar sync task scheduled")

    # Запустить синхронизацию финансов
    app.state.tasks.append(asyncio.create_task(sync_finance_background()))
    logger.info("⏱ Finance sync task scheduled")

    # Запустить фоновую проверку напоминаний
    app.state.tasks.append(asyncio.create_task(poll_reminder_background()))
    logger.info("🚀 All tasks scheduled, startup complete")


@app.on_event("shutdown")
async def shutdown():
    logger.info("🛑 Shutting down application")
    tasks = getattr(app.state, "tasks", [])
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await bot.session.close()


# Регистрировать маршруты
app.include_router(auth_router, dependencies=[Depends(authorize_api)])
app.include_router(sheets_router, dependencies=[Depends(authorize_api)])
app.include_router(finance_router, dependencies=[Depends(authorize_api)])
app.include_router(calendar_router, dependencies=[Depends(authorize_api)])
app.include_router(polling_router, dependencies=[Depends(authorize_api)])
app.include_router(notifications_router, dependencies=[Depends(authorize_api)])
app.include_router(availability_router, dependencies=[Depends(authorize_api)])
app.include_router(planning_router, dependencies=[Depends(authorize_api)])
app.include_router(assistant_router, dependencies=[Depends(authorize_api)])
app.include_router(links_router, dependencies=[Depends(authorize_api)])
app.include_router(afisha_router, dependencies=[Depends(authorize_api)])


@app.get("/")
async def root():
    """Health check"""
    return {
        "status": "ok",
        "service": "Theater Studio Bot API",
        "version": "0.1.0"
    }


@app.get("/health")
async def health():
    """Health check для мониторинга"""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    logger.info(f"🌐 Starting server on {API_HOST}:{API_PORT}")
    uvicorn.run(
        "main:app",
        host=API_HOST,
        port=API_PORT,
        reload=os.getenv("API_RELOAD", "false").lower() == "true",
        log_level=LOG_LEVEL.lower()
    )
