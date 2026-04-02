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
GOOGLE_CALENDAR_JSON = os.getenv("GOOGLE_CALENDAR_JSON", "credentials.json")

# Security
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")

# Admin
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
