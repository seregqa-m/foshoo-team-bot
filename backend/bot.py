"""
Telegram bot для управления театральной студией
Показывает кнопку для открытия Mini App
"""
import logging
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from aiogram.filters import Command
from config import BOT_TOKEN, MINI_APP_URL

logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


@dp.message(Command("start"))
async def cmd_start(message: Message):
    """Обработчик команды /start"""
    logger.info(f"User {message.from_user.id} started bot")

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="🎭 Открыть приложение",
            web_app=WebAppInfo(url=MINI_APP_URL)
        )
    ]])

    await message.answer(
        "Привет! 👋\n\n"
        "Нажми кнопку ниже, чтобы открыть приложение управления театральной студией.",
        reply_markup=kb
    )


@dp.message(Command("help"))
async def cmd_help(message: Message):
    """Обработчик команды /help"""
    await message.answer(
        "📖 Справка\n\n"
        "Доступные команды:\n"
        "/start — главное меню и кнопка приложения\n"
        "/help — эта справка\n\n"
        "Нажми на кнопку 'Открыть приложение' чтобы начать работу!"
    )


@dp.message()
async def echo_handler(message: Message):
    """Обработчик остальных сообщений"""
    await message.answer(
        "Я не понимаю эту команду 😅\n\n"
        "Нажми /start чтобы открыть приложение или /help для справки"
    )
