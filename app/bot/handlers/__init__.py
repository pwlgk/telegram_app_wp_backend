# backend/app/bot/handlers/__init__.py
from aiogram import Dispatcher, Router
import logging

# Импортируем роутеры из других модулей
from .user import user_router

# >>>>> ИМПОРТИРУЕМ РОУТЕР МЕНЕДЖЕРА <<<<<
from .manager import manager_router

logger = logging.getLogger(__name__)

def register_handlers(dp: Dispatcher):
    """
    Регистрирует все роутеры с хендлерами в главном диспетчере.
    """
    # Создаем главный роутер (можно и без него, подключая каждый роутер напрямую к dp)
    main_router = Router(name="main_bot_router")

    # Подключаем дочерние роутеры к главному роутеру
    main_router.include_router(user_router)
    main_router.include_router(manager_router)

    # >>>>> ИЗМЕНЕНИЕ ЗДЕСЬ: Регистрируем ТОЛЬКО главный роутер в диспетчере <<<<<
    dp.include_router(main_router)

    # --- Убираем или комментируем прямое подключение user_router к dp ---
    # dp.include_router(user_router)
    # ------------------------------------------------------------------

    logger.info("Bot message and callback handlers registered successfully via main_router.")