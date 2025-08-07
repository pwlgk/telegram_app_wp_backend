# backend/app/api/v1/endpoints/webhook.py

import logging
from fastapi import APIRouter, Depends, Request, Response, Header, HTTPException, status
from aiogram import Bot, Dispatcher
from aiogram.types import Update
from typing import Annotated

from app.core.config import settings
from app.dependencies import (
    get_bot_instance_dep, 
    get_dispatcher_instance_dep, 
    get_woocommerce_service, 
    get_telegram_service
)
from app.services.woocommerce import WooCommerceService
from app.services.telegram import TelegramService

router = APIRouter()
logger = logging.getLogger(__name__)

@router.post(
    settings.WEBHOOK_PATH or "/", # Путь берется из настроек
    include_in_schema=False, # Не отображать в OpenAPI (Swagger) документации
)
async def telegram_webhook_endpoint(
    request: Request,
    x_telegram_bot_api_secret_token: Annotated[str | None, Header()] = None,
    # Получаем все необходимые экземпляры через систему зависимостей FastAPI
    bot: Bot = Depends(get_bot_instance_dep),
    dp: Dispatcher = Depends(get_dispatcher_instance_dep),
    wc_service: WooCommerceService = Depends(get_woocommerce_service),
    tg_service: TelegramService = Depends(get_telegram_service),
):
    """
    Принимает обновления от Telegram, проверяет токен и передает их диспетчеру Aiogram.
    Вместе с обновлением передает сервисы, чтобы они были доступны в хендлерах.
    """
    # 1. Проверка секретного токена
    if settings.WEBHOOK_SECRET and (not x_telegram_bot_api_secret_token or x_telegram_bot_api_secret_token != settings.WEBHOOK_SECRET):
        logger.warning("Received webhook update with invalid or missing secret token.")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid secret token")

    # 2. Получение и валидация данных обновления
    try:
        update_data = await request.json()
        logger.info(f"--> Received update from Telegram: {update_data}") 
        update_obj = Update(**update_data)
        logger.debug(f"Received update [ID:{update_obj.update_id}] of type '{update_obj.event_type}'")
        logger.debug(f"Update parsed successfully. Type: '{update_obj.event_type}', Update ID: {update_obj.update_id}")

    except Exception as e:
        logger.error(f"Failed to parse incoming update: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid update data")

    # 3. Передача обновления диспетчеру Aiogram с дополнительными данными (сервисами)
    try:
        # Aiogram автоматически прокинет wc_service и tg_service
        # во все хендлеры, которые их запрашивают в своей сигнатуре.
        logger.debug(f"--> Feeding update to dispatcher...")

        await dp.feed_webhook_update(
            bot=bot,
            update=update_obj,
            wc_service=wc_service, # <-- Это передаст wc_service в handle_my_orders
            tg_service=tg_service  # <-- Это передаст tg_service в handle_my_orders
        )
        logger.debug(f"Update [ID:{update_obj.update_id}] successfully processed by dispatcher.")
    except Exception as e:
        # Логируем ошибку, но не выбрасываем HTTP исключение,
        # чтобы Telegram не пытался повторить отправку обновления.
        logger.exception(f"Error processing update [ID:{update_obj.update_id}]: {e}")
        
    # 4. Всегда отвечаем Telegram 200 OK, чтобы он знал, что мы получили обновление.
    return Response(status_code=status.HTTP_200_OK)