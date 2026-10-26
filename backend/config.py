import os
import hashlib
from dotenv import load_dotenv

load_dotenv()

# Bot
BOT_TOKEN = os.getenv("BOT_TOKEN")
TELEGRAM_PROXY_URL = os.getenv("TELEGRAM_PROXY_URL", "").strip() or None
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не установлен в .env")

# API
API_HOST = os.getenv("API_HOST", "127.0.0.1")
API_PORT = int(os.getenv("API_PORT", 8000))
API_URL = os.getenv("API_URL", f"http://{API_HOST}:{API_PORT}")
# First deployment: initialize the local DB, but do not poll or expose API actions.
RECOVERY_MODE = os.getenv("RECOVERY_MODE", "false").lower() == "true"
POLL_AUTOMATION_ENABLED = os.getenv("POLL_AUTOMATION_ENABLED", "true").lower() == "true"

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
SECRET_KEY = os.getenv("SECRET_KEY") or hashlib.sha256(("foshoo-actions:" + BOT_TOKEN).encode()).hexdigest()

# Mini App
MINI_APP_URL = os.getenv("MINI_APP_URL", "https://your-tunnel.trycloudflare.com")

# Admin
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")

# Optional moderation of one public channel's linked discussion group.
# Empty channel disables the feature. Spam removal is automatic by default.
MODERATION_AUTO_DELETE = os.getenv("MODERATION_AUTO_DELETE", "true").strip().lower() == "true"
MODERATION_CHANNEL = os.getenv("MODERATION_CHANNEL", "").strip()
MODERATION_ADMIN_ID = int(os.getenv("MODERATION_ADMIN_ID", "").strip() or ADMIN_ID)

# Telegram Group Chat (для отправки опросов)
GROUP_CHAT_ID = int(os.getenv("GROUP_CHAT_ID", 0))

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# AI Assistant: OpenAI-compatible Foundation Models providers.
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "yandex").strip().lower()
CLOUDRU_API_KEY = os.getenv("CLOUDRU_API_KEY", "")
CLOUDRU_MODEL = os.getenv("CLOUDRU_MODEL", "openai/gpt-oss-120b")
YANDEX_API_KEY = os.getenv("YANDEX_API_KEY", "")
YANDEX_FOLDER_ID = os.getenv("YANDEX_FOLDER_ID", "")
YANDEX_GPT_MODEL = os.getenv("YANDEX_GPT_MODEL", "yandexgpt/latest")
LLM_ENABLED = os.getenv("LLM_ENABLED", "false").lower() == "true"
ASSISTANT_ENABLED = LLM_ENABLED and os.getenv("ASSISTANT_ENABLED", "false").lower() == "true"
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.3"))
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "4096" if LLM_PROVIDER == "cloudru" else "1500"))
# reasoning_effort: low | medium | high (только для reasoning-моделей типа gpt-oss)
LLM_REASONING_EFFORT = os.getenv("LLM_REASONING_EFFORT", "")

# Афиша: ID файлов на Google Drive (не меняются при обновлении содержимого)
AFISHA_NEW_DRIVE_FILE_ID = os.getenv("AFISHA_NEW_DRIVE_FILE_ID", "")
AFISHA_OLD_DRIVE_FILE_ID = os.getenv("AFISHA_OLD_DRIVE_FILE_ID", "")
