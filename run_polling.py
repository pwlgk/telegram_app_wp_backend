# run_polling.py
import asyncio
import logging
from app.core.config import settings
from app.bot.instance import initialize_bot
from app.services.woocommerce import WooCommerceService
from app.services.telegram import TelegramService
from app.bot.utils import set_bot_commands

# Настраиваем логирование так же, как в main.py
log_level = settings.LOGGING_LEVEL.upper()
logging.basicConfig(
    level=log_level,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

async def start_bot_polling():
    """
    Основная функция для запуска бота в режиме Long Polling.
    """
    # 1. Инициализируем бота и диспетчер
    bot, dp = await initialize_bot()
    
    # 2. Инициализируем сервисы
    woo_service = WooCommerceService()
    telegram_service = TelegramService(bot=bot)
    
    # 3. Устанавливаем команды в меню
    await set_bot_commands(bot)

    # 4. Перед запуском опроса, принудительно удаляем вебхук, если он был установлен
    # Это гарантирует, что мы сможем использовать getUpdates.
    try:
        webhook_info = await bot.get_webhook_info()
        if webhook_info.url:
            logger.warning(f"Webhook is active ({webhook_info.url}). Deleting it before starting polling...")
            await bot.delete_webhook(drop_pending_updates=True)
            logger.info("Webhook deleted successfully.")
    except Exception as e:
        logger.error(f"Error deleting webhook: {e}")

    logger.info("Starting bot in Long Polling mode...")

    # 5. Запускаем long polling, передавая наши сервисы в хендлеры
    try:
        # dp.start_polling будет работать вечно, пока не будет остановлен (Ctrl+C)
        await dp.start_polling(
            bot,
            # Aiogram прокинет эти аргументы во все хендлеры, которые их запрашивают
            wc_service=woo_service,
            tg_service=telegram_service
        )
    finally:
        # Этот код выполнится при остановке (Ctrl+C)
        logger.info("Stopping bot...")
        await woo_service.close_client()
        await bot.session.close()
        logger.info("Bot stopped.")


if __name__ == "__main__":
    try:
        asyncio.run(start_bot_polling())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Polling stopped by user.")