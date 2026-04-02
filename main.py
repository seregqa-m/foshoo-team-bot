import asyncio
import logging
import sys
from aiogram import Dispatcher, Bot
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from config import BOT_TOKEN, LOG_LEVEL
from handlers import commands, links

# Настройка логирования
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stdout
)
logger = logging.getLogger(__name__)


async def main():
    """Основная функция запуска бота"""
    # Инициализация бота и диспетчера
    bot = Bot(token=BOT_TOKEN, parse_mode=ParseMode.HTML)
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)

    # Регистрация маршрутизаторов
    dp.include_router(commands.router)
    dp.include_router(links.router)

    logger.info("🤖 Bot started")

    try:
        # Запуск опроса обновлений
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()
        logger.info("🤖 Bot stopped")


if __name__ == "__main__":
    asyncio.run(main())
