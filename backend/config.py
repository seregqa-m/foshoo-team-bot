import os
from dotenv import load_dotenv

load_dotenv()

# Bot
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не установлен в .env")

# API
API_HOST = os.getenv("API_HOST", "127.0.0.1")
API_PORT = int(os.getenv("API_PORT", 8000))
API_URL = os.getenv("API_URL", f"http://{API_HOST}:{API_PORT}")

# Database
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./theater_bot.db")

# Google Calendar API
GOOGLE_CALENDAR_JSON = os.getenv("GOOGLE_CALENDAR_JSON", "backend/credentials.json")
GOOGLE_CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID", "")
SYNC_INTERVAL_MINUTES = int(os.getenv("SYNC_INTERVAL_MINUTES", 15))

# Google Sheets
GOOGLE_SHEETS_ID = os.getenv("GOOGLE_SHEETS_ID", "")
TIMEZONE = os.getenv("TIMEZONE", "Europe/Moscow")

# Security
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")

# Mini App
MINI_APP_URL = os.getenv("MINI_APP_URL", "https://your-tunnel.trycloudflare.com")

# Admin
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")

# Telegram Group Chat (для отправки опросов)
GROUP_CHAT_ID = int(os.getenv("GROUP_CHAT_ID", 0))

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
