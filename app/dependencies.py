# backend/app/dependencies.py
import logging
from datetime import datetime, timezone
import hmac
from fastapi import Request, HTTPException, status, Depends, Header, Security
from fastapi.security import APIKeyHeader
from typing import Annotated, Dict, Optional
from aiogram import Bot, Dispatcher
from app.services.woocommerce import WooCommerceService, WooCommerceServiceError
from app.services.telegram import TelegramService, TelegramNotificationError
from app.utils.telegram_auth import validate_init_data, TelegramAuthError # Импортируем
from app.core.config import settings

# Инициализируем логгер
logger = logging.getLogger(__name__)

# Определяем схему для заголовка X-Admin-API-Key
api_key_header_admin = APIKeyHeader(name="X-Admin-API-Key", auto_error=False)

async def verify_admin_api_key(api_key: str = Security(api_key_header_admin)):
    """
    Зависимость для проверки секретного ключа доступа к админским API.
    Сравнивает значение из заголовка X-Admin-API-Key с ключом из настроек.
    """
    if not settings.ADMIN_API_KEY:
        # Если ключ не настроен на сервере, блокируем доступ к админке
        logger.critical("Admin API Key is not configured on the server!")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Функция администратора временно недоступна."
        )
    if not api_key or not hmac.compare_digest(api_key, settings.ADMIN_API_KEY):
        logger.warning("Invalid or missing Admin API Key received.")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Недействительный или отсутствующий ключ API администратора."
        )
    #logger.debug("Admin API Key verified successfully.")
    return True 

async def get_woocommerce_service(request: Request) -> WooCommerceService:
    service = getattr(request.app.state, 'woocommerce_service', None)
    if not service or not isinstance(service, WooCommerceService):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Сервис WooCommerce недоступен."
        )
    return service

async def get_telegram_service(request: Request) -> TelegramService:
    service = getattr(request.app.state, 'telegram_service', None)
    if not service or not isinstance(service, TelegramService):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Сервис Telegram недоступен."
        )
    return service

# --- Убедитесь, что эти функции здесь есть ---
async def get_bot_instance_dep(request: Request) -> Bot:
    """Зависимость для получения экземпляра Bot из app.state."""
    bot = getattr(request.app.state, 'bot_instance', None)
    if not bot or not isinstance(bot, Bot):
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Экземпляр Telegram бота недоступен.")
    return bot

async def get_dispatcher_instance_dep(request: Request) -> Dispatcher:
    """Зависимость для получения экземпляра Dispatcher из app.state."""
    dp = getattr(request.app.state, 'dispatcher_instance', None)
    if not dp or not isinstance(dp, Dispatcher):
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Диспетчер Telegram бота недоступен.")
    return dp
# --- Конец зависимостей для Bot и Dispatcher ---


# --- Зависимость для валидации Telegram initData ---
async def validate_telegram_data(
    x_telegram_init_data: Annotated[Optional[str], Header(description="Строка initData из Telegram Mini App")] = None
) -> Dict:
    # ... (код функции) ...
    if not x_telegram_init_data:
         raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Отсутствует заголовок X-Telegram-Init-Data.",
        )
    # ... остальная логика валидации ...
    is_valid, parsed_data = validate_init_data(
        init_data=x_telegram_init_data,
        bot_token=settings.TELEGRAM_BOT_TOKEN
    )
    # ... обработка ошибок валидации ...
    if not is_valid or not parsed_data:
         raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Недействительные данные аутентификации Telegram.")

    user_info = parsed_data.get('user')
    if not user_info or not isinstance(user_info, dict) or 'id' not in user_info:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Не удалось извлечь информацию о пользователе Telegram из initData.")

    return parsed_data
# --- Пример использования зависимости валидации в эндпоинте: ---
# @router.post("/some_protected_route")
# async def protected_route(
#     telegram_data: Annotated[Dict, Depends(validate_telegram_data)],
#     # ... другие зависимости и параметры
# ):
#     user_info = telegram_data.get('user')
#     user_id = user_info.get('id')
#     # ... ваша логика
#     return {"message": f"Hello, user {user_id}!"}
