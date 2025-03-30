# backend/app/api/v1/endpoints/webhook.py
import logging
from fastapi import APIRouter, Depends, Request, Response, Header, HTTPException, status
from aiogram import Bot, Dispatcher
from aiogram.types import Update
from typing import Annotated # Для Header

from app.core.config import settings
# Зависимости для получения Bot и Dispatcher (будут брать из app.state)
from app.dependencies import get_bot_instance_dep, get_dispatcher_instance_dep

router = APIRouter()
logger = logging.getLogger(__name__)

@router.post(
    settings.WEBHOOK_PATH or "/",
    include_in_schema=False,
)
async def telegram_webhook_endpoint(
    request: Request, # request нужен для await request.json()
    x_telegram_bot_api_secret_token: Annotated[str | None, Header()] = None,
    # >>>>> ИСПОЛЬЗУЕМ ЗАВИСИМОСТИ НАПРЯМУЮ В ПАРАМЕТРАХ <<<<<
    bot: Bot = Depends(get_bot_instance_dep),
    dp: Dispatcher = Depends(get_dispatcher_instance_dep),
):
    """
    Принимает обновления от Telegram и передает их диспетчеру Aiogram.
    """
    # 1. Проверка секретного токена (если он задан в настройках)
    if settings.WEBHOOK_SECRET:
        if not x_telegram_bot_api_secret_token or x_telegram_bot_api_secret_token != settings.WEBHOOK_SECRET:
            logger.warning("Received webhook update with invalid or missing secret token.")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid secret token")

    # 2. Получение данных обновления
    try:
        update_data = await request.json()
        update_obj = Update(**update_data) # Валидация через Pydantic модель Aiogram
        logger.debug(f"Received update [ID:{update_obj.update_id}] of type '{update_obj.event_type}'")
    except Exception as e:
        logger.error(f"Failed to parse incoming update: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid update data")

    # 3. Передача обновления диспетчеру Aiogram
    # Важно: feed_webhook_update не должен блокироваться надолго.
    # Если обработка сложная, ее нужно выносить в фон (background_tasks или Celery).
    try:
        # Передаем управление диспетчеру
        await dp.feed_webhook_update(bot=bot, update=update_obj)
        logger.debug(f"Update [ID:{update_obj.update_id}] processed by dispatcher.")
    except Exception as e:
        # Логируем ошибку обработки, но Telegram уже не волнует наш ответ на этом этапе
        logger.exception(f"Error processing update [ID:{update_obj.update_id}]: {e}")
        # Не выбрасываем HTTPException, чтобы Telegram не пытался повторить запрос

    # 4. Отвечаем Telegram пустым 200 OK, чтобы подтвердить получение
    return Response(status_code=status.HTTP_200_OK)
