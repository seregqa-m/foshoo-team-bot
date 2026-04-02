import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from keyboards.main_menu import get_main_menu, get_back_button
from config import SERVICES

router = Router()
logger = logging.getLogger(__name__)


@router.message(Command("start"))
async def cmd_start(message: Message):
    """Обработчик команды /start"""
    logger.info(f"User {message.from_user.id} started the bot")

    welcome_text = (
        "👋 Добро пожаловать в управление театральной студией!\n\n"
        "Здесь вы найдёте быстрый доступ к основным сервисам:\n"
    )

    await message.answer(
        welcome_text,
        reply_markup=get_main_menu()
    )


@router.message(Command("help"))
async def cmd_help(message: Message):
    """Обработчик команды /help"""
    help_text = (
        "📖 *Справка*\n\n"
        "Доступные команды:\n"
        "/start — главное меню\n"
        "/help — эта справка\n\n"
        "Выберите нужный сервис из меню ниже:"
    )

    await message.answer(
        help_text,
        reply_markup=get_main_menu(),
        parse_mode="Markdown"
    )


@router.message(F.text == "❓ Справка")
async def help_button(message: Message):
    """Обработчик кнопки справки"""
    help_text = (
        "📖 *Справка*\n\n"
        "*Доступные сервисы:*\n\n"
    )

    for key, service in SERVICES.items():
        help_text += f"• {service['name']} — {service['description']}\n"

    await message.answer(
        help_text,
        reply_markup=get_back_button(),
        parse_mode="Markdown"
    )


@router.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: CallbackQuery):
    """Обработчик кнопки назад"""
    await callback.message.edit_text(
        "👋 Выберите нужный сервис:",
        reply_markup=None
    )

    await callback.message.answer(
        "Выберите сервис из меню:",
        reply_markup=get_main_menu()
    )

    await callback.answer()
