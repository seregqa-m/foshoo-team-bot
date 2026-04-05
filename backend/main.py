"""
Главная точка входа приложения
Запускает FastAPI сервер и Telegram бота
"""
import asyncio
import logging
import sys
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from core.database import init_db, SessionLocal, engine
from config import LOG_LEVEL, API_HOST, API_PORT, GOOGLE_CALENDAR_JSON, GOOGLE_CALENDAR_ID, SYNC_INTERVAL_MINUTES
from modules.calendar.router import router as calendar_router
from modules.calendar.services import CalendarService
from modules.calendar.google_client import GoogleCalendarClient
from modules.polling.router import router as polling_router
from modules.notifications.router import router as notifications_router
from auth_router import router as auth_router
from sheets_router import router as sheets_router
from finance_router import router as finance_router
from links_router import router as links_router
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
    from sqlalchemy import text
    with engine.connect() as conn:
        for stmt in [
            "ALTER TABLE polls ADD COLUMN telegram_poll_id TEXT",
            "ALTER TABLE polls ADD COLUMN telegram_message_id INTEGER",
            "ALTER TABLE polls ADD COLUMN reminder_sent_at DATETIME",
            "ALTER TABLE poll_votes ADD COLUMN username TEXT",
            "ALTER TABLE notification_settings ADD COLUMN reminder_days_before INTEGER DEFAULT 3",
            "ALTER TABLE notification_settings ADD COLUMN reminder_time TEXT DEFAULT '18:00'",
        ]:
            try:
                conn.execute(text(stmt))
                conn.commit()
            except Exception:
                pass  # колонка уже существует


async def _run_bot():
    """Запустить Telegram бота, удалив webhook перед polling"""
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Webhook deleted, starting polling")
        await dp.start_polling(bot, handle_signals=False)
    except Exception as e:
        logger.error(f"❌ Bot polling stopped: {e}", exc_info=True)


# Background sync task для Google Calendar
async def sync_calendar_background():
    """Периодическая синхронизация с Google Calendar"""
    await asyncio.sleep(10)  # Подождать чтобы приложение запустилось

    while True:
        try:
            if os.path.exists(GOOGLE_CALENDAR_JSON) and GOOGLE_CALENDAR_ID:
                google_client = GoogleCalendarClient(GOOGLE_CALENDAR_JSON)
                events = google_client.get_events(GOOGLE_CALENDAR_ID)

                db = SessionLocal()
                try:
                    service = CalendarService(db, google_client)
                    service.sync_from_google(events)
                    logger.info(f"✅ Calendar sync completed: {len(events)} events")
                finally:
                    db.close()
            else:
                logger.debug("Google Calendar not configured, skipping sync")
        except Exception as e:
            logger.error(f"❌ Calendar sync failed: {e}")

        await asyncio.sleep(SYNC_INTERVAL_MINUTES * 60)


async def poll_reminder_background():
    """Проверять каждую минуту: нужно ли отправить напоминание об опросе в группу."""
    await asyncio.sleep(15)

    while True:
        try:
            await _cleanup_old_polls()
        except Exception as e:
            logger.error(f"❌ Poll cleanup failed: {e}")
        try:
            await _check_and_send_reminders()
        except Exception as e:
            logger.error(f"❌ Reminder check failed: {e}")
        await asyncio.sleep(60)


async def _cleanup_old_polls():
    """Удалить опросы у которых событие закончилось вчера или раньше."""
    from datetime import datetime, timedelta
    from modules.polling.models import Poll, PollVote
    from modules.calendar.models import CalendarEvent

    cutoff = datetime.utcnow() - timedelta(days=1)
    db = SessionLocal()
    try:
        old_polls = db.query(Poll).join(
            CalendarEvent, Poll.calendar_event_id == CalendarEvent.id
        ).filter(CalendarEvent.start_time < cutoff).all()

        for poll in old_polls:
            db.query(PollVote).filter(PollVote.poll_id == poll.id).delete()
            db.delete(poll)
        if old_polls:
            db.commit()
            logger.info(f"🗑 Cleaned up {len(old_polls)} old poll(s)")
    finally:
        db.close()


async def _check_and_send_reminders():
    from datetime import datetime, timedelta
    from modules.polling.models import Poll, PollVote
    from modules.notifications.models import NotificationSetting
    from config import ADMIN_ID, GROUP_CHAT_ID, GOOGLE_CALENDAR_JSON, GOOGLE_SHEETS_ID
    import os

    if not GROUP_CHAT_ID:
        return

    now = datetime.utcnow()
    db = SessionLocal()
    try:
        # Читаем настройки напоминаний у администратора
        settings = db.query(NotificationSetting).filter(
            NotificationSetting.user_id == ADMIN_ID
        ).first()
        days_before = settings.reminder_days_before if settings else 3
        reminder_time_str = settings.reminder_time if settings else "18:00"
        if not (settings and settings.poll_reminders_enabled):
            return

        # Проверяем что сейчас нужное время (с точностью до минуты, московское UTC+3)
        moscow_now = now + timedelta(hours=3)
        h, m = map(int, reminder_time_str.split(":"))
        if moscow_now.hour != h or moscow_now.minute != m:
            return

        # Ищем события через days_before дней
        target_date = (now + timedelta(days=days_before)).date()

        # Находим активные опросы с событиями на target_date
        from modules.calendar.models import CalendarEvent
        polls = db.query(Poll).join(
            CalendarEvent, Poll.calendar_event_id == CalendarEvent.id
        ).filter(
            Poll.is_active == True,
            Poll.reminder_sent_at == None,
        ).all()

        # Список названий спектаклей для фильтрации
        show_names_lower = []
        if GOOGLE_SHEETS_ID and os.path.exists(GOOGLE_CALENDAR_JSON):
            try:
                from sheets_client import SheetsClient as _SC
                show_names_lower = [s.lower() for s in _SC(GOOGLE_CALENDAR_JSON, GOOGLE_SHEETS_ID).get_show_names()]
            except Exception:
                pass

        for poll in polls:
            event = db.query(CalendarEvent).filter(CalendarEvent.id == poll.calendar_event_id).first()
            if not event or event.start_time.date() != target_date:
                continue
            # Пропускаем спектакли — посещаемость на них заранее определена
            if show_names_lower and any(s in event.title.lower() for s in show_names_lower):
                continue

            # Кто уже проголосовал (yes/no)
            voted_usernames = {
                v.username.lower() for v in
                db.query(PollVote).filter(
                    PollVote.poll_id == poll.id,
                    PollVote.answer.in_(["yes", "no"]),
                    PollVote.username != None,
                ).all()
                if v.username
            }

            # Все участники труппы из Sheets
            unvoted_mentions = []
            if GOOGLE_SHEETS_ID and os.path.exists(GOOGLE_CALENDAR_JSON):
                try:
                    from sheets_client import SheetsClient
                    client = SheetsClient(GOOGLE_CALENDAR_JSON, GOOGLE_SHEETS_ID)
                    mapping = client.get_actor_mapping()  # {username: actor_name}
                    for username in mapping:
                        if username not in voted_usernames:
                            unvoted_mentions.append(f"@{username}")
                except Exception as e:
                    logger.error(f"Sheets read for reminder failed: {e}")

            if not unvoted_mentions:
                # Все отметились — тоже ставим флаг чтобы не повторять
                poll.reminder_sent_at = now
                db.commit()
                continue

            date_str = event.start_time.strftime("%d.%m в %H:%M")
            mentions = " ".join(unvoted_mentions)

            # Ссылка на опрос
            poll_link = ""
            if poll.telegram_message_id and GROUP_CHAT_ID:
                group_id = str(GROUP_CHAT_ID).lstrip("-").lstrip("100") if str(GROUP_CHAT_ID).startswith("-100") else str(abs(GROUP_CHAT_ID))
                poll_link = f"\nhttps://t.me/c/{group_id}/{poll.telegram_message_id}"

            text = f"ребят, отметьте присутствие {date_str}!\n{mentions}{poll_link}"

            await bot.send_message(chat_id=GROUP_CHAT_ID, text=text)
            poll.reminder_sent_at = now
            db.commit()
            logger.info(f"Reminder sent for poll {poll.id}, event {event.start_time.date()}")

    finally:
        db.close()


# Инициализировать БД
@app.on_event("startup")
async def startup():
    logger.info("🚀 Starting application")
    run_migrations()
    init_db()
    logger.info("✅ Database initialized")

    # Запустить Telegram бота
    asyncio.create_task(_run_bot())
    logger.info("🤖 Telegram bot started")

    # Запустить background sync task для Google Calendar
    asyncio.create_task(sync_calendar_background())

    # Запустить фоновую проверку напоминаний
    asyncio.create_task(poll_reminder_background())


@app.on_event("shutdown")
async def shutdown():
    logger.info("🛑 Shutting down application")


# Регистрировать маршруты
app.include_router(auth_router)
app.include_router(sheets_router)
app.include_router(finance_router)
app.include_router(calendar_router)
app.include_router(polling_router)
app.include_router(notifications_router)
app.include_router(links_router)


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
        reload=True,
        log_level=LOG_LEVEL.lower()
    )
