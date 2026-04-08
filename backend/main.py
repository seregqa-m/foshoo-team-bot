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


async def sync_finance_background():
    """Периодическая синхронизация финансов из Google Sheets."""
    await asyncio.sleep(30)
    while True:
        try:
            from finance_router import sync_finance_from_sheets
            db = SessionLocal()
            try:
                result = sync_finance_from_sheets(db)
                if not result.get("skipped"):
                    logger.info(f"✅ Finance sync: {result}")
            finally:
                db.close()
        except Exception as e:
            logger.error(f"❌ Finance sync failed: {e}")
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

    now = datetime.utcnow()
    db = SessionLocal()
    try:
        settings = db.query(NotificationSetting).filter(
            NotificationSetting.user_id == ADMIN_ID
        ).first()
        if not (settings and settings.poll_reminders_enabled):
            return

        moscow_now = now + timedelta(hours=3)
        h, m = map(int, settings.reminder_time.split(":"))
        if (moscow_now.hour, moscow_now.minute) < (h, m):
            return

        target_date = (now + timedelta(days=settings.reminder_days_before)).date()

        show_names_lower = []
        if GOOGLE_SHEETS_ID and os.path.exists(GOOGLE_CALENDAR_JSON):
            try:
                from sheets_client import SheetsClient as _SC
                show_names_lower = [s.lower() for s in _SC(GOOGLE_CALENDAR_JSON, GOOGLE_SHEETS_ID).get_show_names()]
            except Exception:
                pass

        for event in db.query(CalendarEvent).all():
            if event.start_time.date() != target_date:
                continue
            if show_names_lower and any(s in event.title.lower() for s in show_names_lower):
                continue
            from config import TROUPE_FILTER
            if TROUPE_FILTER not in event.title.lower():
                continue
            existing = db.query(Poll).filter(
                Poll.calendar_event_id == event.id,
                Poll.is_active == True,
            ).first()
            if existing:
                continue

            from babel.dates import format_date
            dt = event.start_time
            date_str = f"в {format_date(dt, 'EEEE', locale='ru_RU')} {format_date(dt, 'd MMM', locale='ru_RU')} в {dt.strftime('%H:%M')}"

            poll_service = PollingService(db)
            poll = poll_service.create_poll(
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

    now = datetime.utcnow()
    db = SessionLocal()
    try:
        settings = db.query(NotificationSetting).filter(
            NotificationSetting.user_id == ADMIN_ID
        ).first()
        reminder_time_str = settings.reminder_time if settings else "18:00"
        if not (settings and settings.poll_reminders_enabled):
            return

        moscow_now = now + timedelta(hours=3)
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

            unvoted_mentions = []
            if GOOGLE_SHEETS_ID and os.path.exists(GOOGLE_CALENDAR_JSON):
                try:
                    from sheets_client import SheetsClient
                    client = SheetsClient(GOOGLE_CALENDAR_JSON, GOOGLE_SHEETS_ID)
                    for username in client.get_actor_mapping():
                        if username not in voted_usernames:
                            unvoted_mentions.append(f"@{username}")
                except Exception as e:
                    logger.error(f"Sheets read for reminder failed: {e}")

            if not unvoted_mentions:
                poll.reminder_sent_at = now
                db.commit()
                continue

            date_str = event.start_time.strftime("%d.%m в %H:%M")
            mentions = " ".join(unvoted_mentions)
            poll_link = ""
            if poll.telegram_message_id and GROUP_CHAT_ID:
                group_id = str(GROUP_CHAT_ID).lstrip("-").lstrip("100") if str(GROUP_CHAT_ID).startswith("-100") else str(abs(GROUP_CHAT_ID))
                poll_link = f"\nhttps://t.me/c/{group_id}/{poll.telegram_message_id}"

            await bot.send_message(chat_id=GROUP_CHAT_ID,
                                   text=f"ребят, отметьте присутствие {date_str}!\n{mentions}{poll_link}")

            if poll.telegram_message_id:
                try:
                    await bot.pin_chat_message(chat_id=GROUP_CHAT_ID,
                                               message_id=poll.telegram_message_id,
                                               disable_notification=True)
                except Exception as e:
                    logger.warning(f"Pin poll failed: {e}")

            poll.reminder_sent_at = now
            db.commit()
            logger.info(f"✅ Reminder sent for poll {poll.id}, event {event.start_time.date()}")

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

    # Запустить синхронизацию финансов
    asyncio.create_task(sync_finance_background())

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
