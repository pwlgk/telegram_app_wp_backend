# backend/app/bot/instance.py

import logging
from aiogram.fsm.storage.memory import MemoryStorage # Для состояний

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from app.bot.handlers.manager import manager_router # <<< Импортируем

from app.core.config import settings
# Импорты роутеров
from app.bot.handlers.user import user_router
from app.bot.handlers.callbacks import callback_router
# Импорт Middleware
from app.bot.middleware import LoggingMiddleware

logger = logging.getLogger(__name__)

async def initialize_bot() -> tuple[Bot, Dispatcher]:
    """
    Инициализирует и настраивает бота и диспетчер, регистрирует роутеры.
    """
    default_properties = DefaultBotProperties(
        parse_mode=ParseMode.HTML
    )
    storage = MemoryStorage() # Используем хранилище в памяти

    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN, default=default_properties)
    dp = Dispatcher(storage=storage) # <<< Передаем storage

    # Регистрация Middleware
    dp.update.outer_middleware(LoggingMiddleware())
    logger.info("LoggingMiddleware registered.")

    # Регистрация роутеров
    dp.include_router(user_router)
    dp.include_router(manager_router) # <<< Регистрируем

    dp.include_router(callback_router)

    
    logger.info("Bot handlers registered: user_router, callback_router.")

    try:
        # Проверяем соединение с Telegram API и получаем информацию о боте
        bot_info = await bot.get_me()
        
        # =======================================================================
        # <<< ВОТ ЭТОТ ЛОГ ВЫВЕДЕТ ИМЯ БОТА ПРИ ЗАПУСКЕ >>>
        logger.info(f"Bot initialized: ID={bot_info.id}, Username='{bot_info.username}'")
        # =======================================================================

    except Exception as e:
        logger.exception(f"Failed to connect to Telegram API: {e}")
        # Если бот не может подключиться, нет смысла запускать приложение
        raise RuntimeError("Could not initialize Telegram Bot connection") from e

    logger.info("Aiogram Bot and Dispatcher initialized successfully.")
    return bot, dp

async def shutdown_bot(bot: Bot | None):
    """
    Корректно закрывает сессию бота.
    """
    if bot:
        logger.info("Shutting down bot session...")
        try:
            await bot.session.close()
            logger.info("Bot session closed.")
        except Exception as e:
            logger.error(f"Error closing bot session: {e}", exc_info=True)
    else:
         logger.warning("Bot instance not found, skipping shutdown.")