from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from config import SERVICES


def get_main_menu() -> ReplyKeyboardMarkup:
    """Главное меню с кнопками сервисов"""
    buttons = [
        [KeyboardButton(text=service["name"])]
        for service in SERVICES.values()
    ]
    buttons.append([KeyboardButton(text="❓ Справка")])

    return ReplyKeyboardMarkup(
        keyboard=buttons,
        resize_keyboard=True,
        one_time_keyboard=False
    )


def get_service_inline_menu(service_key: str) -> InlineKeyboardMarkup:
    """Inline меню для конкретного сервиса"""
    service = SERVICES.get(service_key)
    if not service:
        return None

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔗 Перейти", url=service["url"])],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
        ]
    )


def get_back_button() -> InlineKeyboardMarkup:
    """Кнопка назад в главное меню"""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
        ]
    )
