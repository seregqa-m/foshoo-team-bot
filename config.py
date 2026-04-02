import os
from dotenv import load_dotenv

load_dotenv()

# Telegram Bot
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не установлен в файле .env")

ADMIN_ID = int(os.getenv("ADMIN_ID", 0))

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# External Services (ссылки на сервисы)
SERVICES = {
    "schedule": {
        "name": "📅 Расписание",
        "url": "https://example.com/schedule",
        "description": "Расписание занятий и репетиций"
    },
    "finance": {
        "name": "💰 Финансы",
        "url": "https://example.com/finance",
        "description": "Смета и финансовые отчеты"
    },
    "documents": {
        "name": "📄 Документы",
        "url": "https://example.com/documents",
        "description": "Важные документы и контракты"
    },
    "gallery": {
        "name": "🖼️ Галерея",
        "url": "https://example.com/gallery",
        "description": "Фото и видео материалы"
    },
    "team": {
        "name": "👥 Команда",
        "url": "https://example.com/team",
        "description": "Контакты и информация о членах студии"
    },
}
