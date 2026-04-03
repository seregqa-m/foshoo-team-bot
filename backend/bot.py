"""
Telegram bot для управления театральной студией
Показывает кнопку для открытия Mini App
"""
import logging
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo, PollAnswer
from aiogram.filters import Command
from config import BOT_TOKEN, MINI_APP_URL

logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


@dp.message(Command("start"))
async def cmd_start(message: Message):
    """Обработчик команды /start"""
    logger.info(f"User {message.from_user.id} started bot")

    if message.chat.type == "private":
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
    else:
        await message.answer(
            "Привет! 👋\n\n"
            "Чтобы открыть приложение, напиши мне в личные сообщения: @" +
            (await message.bot.get_me()).username
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


_POLL_ANSWER_MAP = {0: "yes", 1: "no", 2: "maybe"}


@dp.poll_answer()
async def handle_poll_answer(poll_answer: PollAnswer):
    """Сохранить ответ на Telegram-опрос в БД"""
    from core.database import SessionLocal
    from modules.polling.services import PollingService
    from modules.polling.models import Poll

    if not poll_answer.option_ids:
        return  # пользователь отозвал голос

    answer = _POLL_ANSWER_MAP.get(poll_answer.option_ids[0])
    if not answer:
        logger.warning(f"Unknown poll option index: {poll_answer.option_ids[0]}")
        return

    db = SessionLocal()
    try:
        poll = db.query(Poll).filter(Poll.telegram_poll_id == poll_answer.poll_id).first()
        if not poll:
            logger.warning(f"No DB poll for telegram_poll_id={poll_answer.poll_id}")
            return
        PollingService(db).vote(poll.id, poll_answer.user.id, answer)
        logger.info(f"Poll vote saved: poll={poll.id} user={poll_answer.user.id} answer={answer}")
    except Exception as e:
        logger.error(f"poll_answer handler error: {e}")
    finally:
        db.close()


@dp.message()
async def echo_handler(message: Message):
    """Обработчик остальных сообщений"""
    await message.answer(
        "Я не понимаю эту команду 😅\n\n"
        "Нажми /start чтобы открыть приложение или /help для справки"
    )
