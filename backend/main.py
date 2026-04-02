"""
Главная точка входа приложения
Запускает FastAPI сервер и Telegram бота
"""
import asyncio
import logging
import sys
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from core.database import init_db
from config import LOG_LEVEL, API_HOST, API_PORT
from modules.calendar.router import router as calendar_router
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

# Инициализировать БД
@app.on_event("startup")
async def startup():
    logger.info("🚀 Starting application")
    init_db()
    logger.info("✅ Database initialized")


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
