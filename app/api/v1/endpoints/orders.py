# backend/app/api/v1/endpoints/orders.py
import logging
from fastapi import APIRouter, Depends, HTTPException, status, Body, BackgroundTasks
from typing import List, Optional, Dict, Annotated

from app.services.woocommerce import WooCommerceService, WooCommerceServiceError
from app.services.telegram import TelegramService, TelegramNotificationError
from app.models.order import OrderCreateWooCommerce, LineItemCreate, MetaData, OrderWooCommerce, BillingAddress, CouponLine
from app.models.common import MetaData as CommonMetaData # Используем общую модель
from app.dependencies import get_woocommerce_service, get_telegram_service, validate_telegram_data
from app.core.config import settings
from pydantic import BaseModel, Field # Импорт BaseModel и Field

logger = logging.getLogger(__name__)

router = APIRouter()

# Модель для тела запроса от фронтенда
class OrderPayload(BaseModel):
    line_items: List[LineItemCreate] = Field(..., min_length=1) # Корзина не должна быть пустой
    customer_note: Optional[str] = None
    coupon_code: Optional[str] = None

@router.post(
    "/", # Префикс /orders будет добавлен в api/v1/router.py
    response_model=OrderWooCommerce, # Возвращаем модель созданного заказа WC
    summary="Создать новый заказ",
    description="Принимает данные корзины из Mini App, валидирует пользователя Telegram, создает заказ в WooCommerce и уведомляет менеджеров.",
    status_code=status.HTTP_201_CREATED,
)
async def create_new_order(
    payload: OrderPayload,
    background_tasks: BackgroundTasks, # Для фоновой отправки уведомлений
    telegram_data: Annotated[Dict, Depends(validate_telegram_data)], # Зависимость для валидации TG
    wc_service: WooCommerceService = Depends(get_woocommerce_service),
    tg_service: TelegramService = Depends(get_telegram_service),
):
    """
    Создает заказ в WooCommerce и ставит задачу отправки уведомления менеджерам в фон.
    """
    user_info = telegram_data.get('user', {})
    tg_user_id = user_info.get('id')
    tg_username = user_info.get('username')
    tg_first_name = user_info.get('first_name', '')
    tg_last_name = user_info.get('last_name', '')

    logger.info(f"Processing order creation request for Telegram user ID: {tg_user_id}, Username: {tg_username}")
    
    coupon_lines_data: Optional[List[CouponLine]] = None
    coupon_code_from_payload = payload.coupon_code
    logger.info(f"Coupon code from payload: {coupon_code_from_payload}") # 
    if coupon_code_from_payload:
        coupon_lines_data = [CouponLine(code=coupon_code_from_payload)]
        logger.info(f"Applying coupon code from payload: {coupon_code_from_payload}") # Добавим лог
    else:
        logger.info("No coupon code provided in payload.") # Добавим лог

    # 1. Подготовка метаданных для заказа WC
    order_meta_data = [
        CommonMetaData(key="_telegram_user_id", value=str(tg_user_id)),
        CommonMetaData(key="_telegram_username", value=tg_username or ""),
        CommonMetaData(key="_telegram_first_name", value=tg_first_name),
        CommonMetaData(key="_telegram_last_name", value=tg_last_name),
        CommonMetaData(key="_created_via", value="Telegram Mini App"),
    ]

    # 2. (Опционально) Заполнение Billing Address из данных TG
    billing_address = BillingAddress(
        first_name=tg_first_name or "Telegram User", # WC требует имя
        last_name=tg_last_name or str(tg_user_id),
        # Генерируем временный email, если WC требует (проверьте настройки WC)
        # email=f"tg_{tg_user_id}@telegram.user"
    )

    # 3. Формирование данных для создания заказа в WC
    order_data_wc = OrderCreateWooCommerce(
        payment_method="cod",
        payment_method_title="Согласование с менеджером (Telegram)",
        set_paid=False,
        status="on-hold", # Статус "На удержании"
        line_items=payload.line_items,
        customer_note=payload.customer_note,
        customer_id=0, # Гостевой заказ
        meta_data=order_meta_data,
        billing=billing_address, # Передаем заполненный адрес
        coupon_lines=coupon_lines_data
        # shipping=... # Можно скопировать из billing или оставить пустым
    )

    # 4. Создание заказа через сервис WooCommerce
    try:
        logger.info(f"Created Order Data: {order_data_wc}")
        created_order = await wc_service.create_order(order_data_wc)
        
        if not created_order or not isinstance(created_order, dict):
             # Это не должно произойти, т.к. сервис кидает исключения
             logger.error("WooCommerce service returned unexpected result after creating order.")
             raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Не удалось создать заказ (внутренняя ошибка).")

        order_id = created_order.get("id")
        logger.info(f"Order ID {order_id} created successfully in WooCommerce for user {tg_user_id}.")

    except WooCommerceServiceError as e:
        logger.error(f"Failed to create order in WooCommerce for user {tg_user_id}: {e}")
        raise HTTPException(status_code=e.status_code or 503, detail=f"Ошибка WooCommerce: {e.message}")
    except Exception as e:
         logger.exception(f"Unexpected error during order creation for user {tg_user_id}: {e}")
         raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Непредвиденная ошибка при создании заказа.")

    # 5. Отправка уведомления менеджерам в фоновом режиме
    # Используем BackgroundTasks, чтобы не задерживать ответ клиенту
    try:
        background_tasks.add_task(
            tg_service.notify_new_order,
            order_details=created_order, # Передаем весь созданный заказ
            user_info=user_info # Передаем инфо о пользователе
        )
        logger.info(f"Notification task for order {order_id} added to background.")
    except Exception as e:
         # Логируем ошибку добавления задачи, но не прерываем процесс
         logger.exception(f"Failed to add notification task for order {order_id}: {e}")

    # 6. Возвращаем данные созданного заказа (валидированные через Pydantic)
    try:
         validated_order_response = OrderWooCommerce.model_validate(created_order)
         return validated_order_response
    except Exception as e:
        logger.error(f"Failed to validate WooCommerce order response for order {order_id}: {e}. Returning raw data.")
        # Возвращаем "сырой" ответ, если валидация Pydantic не удалась
        return created_order
