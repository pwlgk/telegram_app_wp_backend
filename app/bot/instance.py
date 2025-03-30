# backend/app/bot/instance.py
import logging
from typing import Optional, Tuple
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
# >>>>> ИМПОРТИРУЕМ DefaultBotProperties <<<<<
from aiogram.client.default import DefaultBotProperties
# from aiogram.fsm.storage.memory import MemoryStorage # Если нужен FSM

from app.core.config import settings
from app.bot.handlers import register_handlers

logger = logging.getLogger(__name__)

_bot_instance: Optional[Bot] = None
_dispatcher_instance: Optional[Dispatcher] = None

async def initialize_bot() -> Tuple[Bot, Dispatcher]:
    """Инициализирует Bot, Dispatcher и регистрирует хендлеры."""
    global _bot_instance, _dispatcher_instance

    if _bot_instance and _dispatcher_instance:
        logger.warning("Bot and Dispatcher already initialized.")
        return _bot_instance, _dispatcher_instance

    # >>>>> ИЗМЕНЯЕМ СПОСОБ ПЕРЕДАЧИ parse_mode <<<<<
    # Создаем объект с настройками по умолчанию
    default_properties = DefaultBotProperties(
        parse_mode=ParseMode.HTML
        # Здесь можно добавить другие дефолтные настройки, если нужно:
        # disable_web_page_preview=True,
        # protect_content=False
    )
    # Передаем настройки через параметр default
    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN, default=default_properties)
    # >>>>> КОНЕЦ ИЗМЕНЕНИЙ <<<<<

    # storage = MemoryStorage() # Пример
    # dp = Dispatcher(storage=storage)
    dp = Dispatcher()

    register_handlers(dp)

    _bot_instance = bot
    _dispatcher_instance = dp

    try:
        bot_info = await bot.get_me()
        logger.info(f"Bot initialized: ID={bot_info.id}, Username={bot_info.username}")
    except Exception as e:
        logger.exception(f"Failed to connect to Telegram API: {e}")
        raise RuntimeError("Could not initialize Telegram Bot connection") from e

    logger.info("Aiogram Bot and Dispatcher initialized successfully.")
    return bot, dp

async def shutdown_bot(bot: Optional[Bot] = None, dp: Optional[Dispatcher] = None):
    """Корректно останавливает сессию бота."""
    global _bot_instance, _dispatcher_instance
    bot_to_close = bot or _bot_instance

    if bot_to_close:
        logger.info("Shutting down bot session...")
        try:
            await bot_to_close.session.close()
            logger.info("Bot session closed.")
        except Exception as e:
            logger.error(f"Error closing bot session: {e}")
    else:
         logger.warning("Bot instance not found for shutdown.")

    _bot_instance = None
    _dispatcher_instance = None


def get_bot_instance() -> Optional[Bot]:
    return _bot_instance

def get_dispatcher_instance() -> Optional[Dispatcher]:
    return _dispatcher_instance