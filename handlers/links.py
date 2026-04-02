import logging
from aiogram import Router, F
from aiogram.types import Message
from keyboards.main_menu import get_service_inline_menu, get_main_menu
from config import SERVICES

router = Router()
logger = logging.getLogger(__name__)


async def handle_service_click(message: Message, service_key: str):
    """Обработчик клика на сервис"""
    service = SERVICES.get(service_key)

    if not service:
        await message.answer("❌ Сервис не найден")
        return

    logger.info(f"User {message.from_user.id} clicked on {service_key}")

    text = (
        f"🔗 *{service['name']}*\n\n"
        f"{service['description']}\n\n"
        "Нажмите кнопку ниже, чтобы перейти:"
    )

    await message.answer(
        text,
        reply_markup=get_service_inline_menu(service_key),
        parse_mode="Markdown"
    )


# Регистрируем обработчики для каждого сервиса
for key, service in SERVICES.items():
    @router.message(F.text == service["name"])
    async def service_handler(message: Message, service_key=key):
        await handle_service_click(message, service_key)
