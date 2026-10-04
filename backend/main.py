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
from modules.calendar.classification import classify_event, is_performance, is_troupe_event
from modules.polling.router import router as polling_router
from modules.notifications.router import router as notifications_router
from modules.availability.router import router as availability_router
from modules.planning.router import router as planning_router
from modules.admin.router import router as admin_router
from modules.theater.router import router as theater_router
import modules.attendance.models  # noqa: common person/day answers must survive poll cleanup
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
            "ALTER TABLE polls ADD COLUMN telegram_chat_id BIGINT",
            "ALTER TABLE polls ADD COLUMN selected_date DATE",
            "ALTER TABLE polls ADD COLUMN show_id INTEGER",
            "ALTER TABLE polls ADD COLUMN delivery_state TEXT",
            "ALTER TABLE availability_campaigns ADD COLUMN request_key TEXT",
            "ALTER TABLE availability_polls ADD COLUMN telegram_chat_id BIGINT",
            "ALTER TABLE availability_polls ADD COLUMN show_names TEXT",
            "ALTER TABLE availability_polls ADD COLUMN delivery_state TEXT",
            "ALTER TABLE availability_votes ADD COLUMN option_ids TEXT",
            "ALTER TABLE calendar_events ADD COLUMN poll_show_id INTEGER",
            "ALTER TABLE calendar_events ADD COLUMN poll_show_title TEXT",
        ]:
            table, column = stmt.split()[2], stmt.split()[5]
            if column not in {c["name"] for c in inspect(conn).get_columns(table)}:
                conn.execute(text(stmt))
        # Snapshot legacy destinations/dates once; future event moves must not move votes.
        from config import GROUP_CHAT_ID
        if GROUP_CHAT_ID:
            for table in ('polls', 'availability_polls'):
                conn.execute(text(f'UPDATE {table} SET telegram_chat_id=:chat WHERE telegram_chat_id IS NULL AND telegram_message_id IS NOT NULL'), {'chat': GROUP_CHAT_ID})
        conn.execute(text('UPDATE polls SET selected_date=(SELECT substr(start_time, 1, 10) FROM calendar_events WHERE calendar_events.id=polls.calendar_event_id) WHERE selected_date IS NULL'))
        conn.execute(text('UPDATE availability_poll_options SET selected_date=(SELECT substr(start_time, 1, 10) FROM calendar_events WHERE calendar_events.id=availability_poll_options.calendar_event_id) WHERE selected_date IS NULL'))


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
            or classify_event(e.title, show_names_lower)["show_name"]
            or is_performance(e.title, show_names_lower)
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
    return SheetsClient(GOOGLE_CALENDAR_JSON, GOOGLE_SHEETS_ID).get_show_names()


def _reminder_usernames(db, show_name):
    from config import GOOGLE_SHEETS_ID
    from sheets_client import SheetsClient
    from modules.theater.routing import cast_usernames
    if not (GOOGLE_SHEETS_ID and os.path.exists(GOOGLE_CALENDAR_JSON)):
        raise RuntimeError('Google Sheets is not configured')
    return cast_usernames(db, [show_name], SheetsClient(GOOGLE_CALENDAR_JSON, GOOGLE_SHEETS_ID))


def _export_attendance():
    from modules.attendance.services import export_pending
    with SessionLocal() as db:
        export_pending(db)


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
        try:
            await asyncio.to_thread(_export_attendance)
        except Exception:
            logger.exception('Attendance export failed; will retry')
        await asyncio.sleep(60)


async def _cleanup_old_polls():
    """Archive expired publications while retaining their vote history."""
    from datetime import datetime, timedelta
    from modules.polling.models import Poll, PollVote
    from modules.calendar.models import CalendarEvent

    cutoff = local_now() - timedelta(days=1)
    db = SessionLocal()
    try:
        old_polls = db.query(Poll).join(
            CalendarEvent, Poll.calendar_event_id == CalendarEvent.id
        ).filter(CalendarEvent.end_time < cutoff, Poll.is_active == True).all()

        for poll in old_polls:
            poll.is_active = False
        if old_polls:
            db.commit()
            logger.info(f"🗑 Cleaned up {len(old_polls)} old poll(s)")
    finally:
        db.close()


def _poll_settings(db):
    from config import ADMIN_ID
    from modules.notifications.models import NotificationSetting
    settings = db.query(NotificationSetting).filter_by(user_id=ADMIN_ID).first()
    if not settings or not settings.poll_reminders_enabled:
        return None
    now = local_now()
    if (now.hour, now.minute) < tuple(map(int, settings.reminder_time.split(':'))):
        return None
    return settings


async def _auto_create_polls():
    from datetime import timedelta
    from config import ADMIN_ID, TROUPE_FILTER
    from modules.calendar.models import CalendarEvent
    from modules.theater.routing import show_aliases, saved_event_show
    from modules.polling.delivery import publish_event
    with SessionLocal() as db:
        settings = _poll_settings(db)
        if not settings:
            return
        now = local_now().date()
        target = now + timedelta(days=settings.reminder_days_before)
        aliases = list(show_aliases(db))
        for event in db.query(CalendarEvent).filter_by(is_cancelled=False).all():
            if not now <= event.start_time.date() <= target:
                continue
            if not (is_troupe_event(event.title, aliases, settings.troupe_filter or TROUPE_FILTER)
                    or (saved_event_show(db, event) and not is_performance(event.title, aliases))):
                continue
            try:
                await publish_event(db, bot, event, ADMIN_ID, automatic=True)
            except Exception as exc:
                logger.warning('Auto poll skipped for event %s: %s', event.id, exc)


async def _send_poll_reminders():
    from datetime import datetime, timedelta
    from config import ADMIN_ID, TROUPE_FILTER
    from modules.calendar.models import CalendarEvent
    from modules.polling.models import Poll
    from modules.polling.delivery import publish_event
    from modules.theater.routing import event_destination, poll_link, show_aliases, saved_event_show
    from modules.attendance.services import answered_usernames
    with SessionLocal() as db:
        settings = _poll_settings(db)
        if not settings:
            return
        target = (local_now() + timedelta(days=1)).date()
        aliases = list(show_aliases(db))
        recipients = {}
        for event in db.query(CalendarEvent).filter_by(is_cancelled=False).all():
            if event.start_time.date() != target:
                continue
            if not (is_troupe_event(event.title, aliases, settings.troupe_filter or TROUPE_FILTER)
                    or (saved_event_show(db, event) and not is_performance(event.title, aliases))):
                continue
            try:
                show = event_destination(db, event)
                result = await publish_event(db, bot, event, ADMIN_ID, automatic=True)
                poll = db.get(Poll, result['poll_id'])
                if not poll.is_active or poll.reminder_sent_at:
                    continue
                if show.id not in recipients:
                    recipients[show.id] = await asyncio.to_thread(_reminder_usernames, db, show.name)
                missing = recipients[show.id] - answered_usernames(db, target)
                db.refresh(show)
                if show.telegram_chat_id != poll.telegram_chat_id:
                    continue
                if missing:
                    link = poll_link(poll.telegram_chat_id, poll.telegram_message_id)
                    text = f'{show.name}: отметьте присутствие {event.start_time:%d.%m в %H:%M}!\n' + ' '.join('@' + u for u in sorted(missing))
                    if link:
                        text += '\n\n' + link
                    await bot.send_message(chat_id=poll.telegram_chat_id, text=text)
                poll.reminder_sent_at = datetime.utcnow()
                db.commit()
                try:
                    await bot.pin_chat_message(chat_id=poll.telegram_chat_id, message_id=poll.telegram_message_id, disable_notification=True)
                except Exception:
                    logger.warning('Could not pin poll %s', poll.id)
            except Exception as exc:
                logger.warning('Reminder skipped for event %s: %s', event.id, exc)


# Инициализировать БД
@app.on_event("startup")
async def startup():
    logger.info("🚀 Starting application")
    import modules.availability.models  # noqa: ensure tables created
    import modules.planning.models  # noqa: durable calendar/schedule operations
    import modules.assistant.models  # noqa: ensure assistant_action_log table created
    import modules.moderation.models  # noqa: ensure moderation_comments table created
    logger.info("⏱ Running migrations...")
    init_db()
    run_migrations()
    from core.database import SessionLocal
    from modules.admin.services import bootstrap_superadmin
    from config import ADMIN_ID
    with SessionLocal() as db:
        bootstrap_superadmin(db, ADMIN_ID)
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
app.include_router(admin_router, dependencies=[Depends(authorize_api)])
app.include_router(theater_router, dependencies=[Depends(authorize_api)])
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
