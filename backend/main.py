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
from core.database import init_db, SessionLocal
from config import LOG_LEVEL, API_HOST, API_PORT, GOOGLE_CALENDAR_JSON, GOOGLE_CALENDAR_ID, SYNC_INTERVAL_MINUTES
from modules.calendar.router import router as calendar_router
from modules.calendar.services import CalendarService
from modules.calendar.google_client import GoogleCalendarClient
from modules.polling.router import router as polling_router
from modules.notifications.router import router as notifications_router

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


# Инициализировать БД
@app.on_event("startup")
async def startup():
    logger.info("🚀 Starting application")
    init_db()
    logger.info("✅ Database initialized")

    # Запустить background sync task
    asyncio.create_task(sync_calendar_background())


@app.on_event("shutdown")
async def shutdown():
    logger.info("🛑 Shutting down application")


# Регистрировать маршруты
app.include_router(calendar_router)
app.include_router(polling_router)
app.include_router(notifications_router)


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
