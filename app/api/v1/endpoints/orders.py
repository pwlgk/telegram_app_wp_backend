# backend/app/api/v1/endpoints/orders.py
import logging
from fastapi import APIRouter, Depends, HTTPException, status, Body, BackgroundTasks
from typing import List, Optional, Dict, Annotated
from app.models.common import MetaData, BillingInfo

from app.services.woocommerce import WooCommerceService, WooCommerceServiceError
from app.services.telegram import TelegramService, TelegramNotificationError
from app.models.order import OrderCreateWooCommerce, LineItemCreate, MetaData, OrderWooCommerce, CouponLine
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
    billing: Optional[BillingInfo] = None # <<< ДОБАВЛЯЕМ ЭТО ПОЛЕ


@router.post(
    "/",
    response_model=OrderWooCommerce,
    summary="Создать новый заказ",
    description="Принимает данные корзины и покупателя, создает/обновляет пользователя, создает заказ и уведомляет менеджеров.",
    status_code=status.HTTP_201_CREATED,
)
async def create_new_order(
    payload: OrderPayload,
    background_tasks: BackgroundTasks,
    telegram_data: Annotated[Dict, Depends(validate_telegram_data)],
    wc_service: WooCommerceService = Depends(get_woocommerce_service),
    tg_service: TelegramService = Depends(get_telegram_service),
):
    user_info = telegram_data.get('user', {})
    tg_user_id = user_info.get('id')
    logger.info(f"Processing order creation request for Telegram user ID: {tg_user_id}")

    # 1. Найти или создать пользователя и получить его customer_id
    customer_id = await wc_service.find_or_create_customer_by_telegram_data(user_info)

    if not customer_id:
        logger.critical(f"Failed to resolve a customer ID for Telegram user {tg_user_id}. Aborting order creation.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Не удалось обработать данные пользователя. Попробуйте позже."
        )
    
    # 2. (Опционально, но рекомендуется) Обновить профиль пользователя данными из заказа
    if payload.billing:
        update_data = payload.billing.model_dump(exclude_unset=True)
        # Мы можем обновить профиль пользователя в фоне, чтобы не задерживать создание заказа
        if update_data:
            logger.info(f"Adding task to update customer {customer_id} profile with new billing info.")
            background_tasks.add_task(
                wc_service.update_customer,
                customer_id=customer_id,
                data_to_update={"billing": update_data}
            )

    coupon_lines_data: Optional[List[CouponLine]] = None
    if payload.coupon_code:
        coupon_lines_data = [CouponLine(code=payload.coupon_code)]

    # 3. Подготовка метаданных для заказа WC (остается полезной для быстрого доступа)
    order_meta_data = [
        CommonMetaData(key="_telegram_user_id", value=str(tg_user_id)),
        CommonMetaData(key="_telegram_username", value=user_info.get('username') or ""),
        CommonMetaData(key="_created_via", value="Telegram Mini App"),
    ]

    # 4. Формирование данных для создания заказа в WC
    # Мы явно передаем billing info в заказ, чтобы гарантировать,
    # что именно эти данные будут в нем, а не старые из профиля WP.
    order_data_wc = OrderCreateWooCommerce(
        payment_method="cod",
        payment_method_title="Согласование с менеджером (Telegram)",
        set_paid=False,
        status="on-hold",
        line_items=payload.line_items,
        # Явно передаем данные биллинга
        billing=payload.billing, 
        # customer_note теперь используется по прямому назначению
        customer_note=payload.customer_note, 
        customer_id=customer_id,
        meta_data=order_meta_data,
        coupon_lines=coupon_lines_data
    )

    # 5. Создание заказа через сервис WooCommerce
    try:
        logger.debug(f"Creating order with data: {order_data_wc.model_dump_json(indent=2)}")
        created_order = await wc_service.create_order(order_data_wc)
        
        if not created_order or not isinstance(created_order, dict):
             raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Не удалось создать заказ (внутренняя ошибка).")

        order_id = created_order.get("id")
        logger.info(f"Order ID {order_id} created successfully for customer_id {customer_id} (TG user {tg_user_id}).")

    except WooCommerceServiceError as e:
        logger.error(f"Failed to create order in WooCommerce for customer {customer_id}: {e}")
        raise HTTPException(status_code=e.status_code or 503, detail=f"Ошибка WooCommerce: {e.message}")
    except Exception as e:
         logger.exception(f"Unexpected error during order creation for customer {customer_id}: {e}")
         raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Непредвиденная ошибка при создании заказа.")

    # 6. Запуск фоновых задач (уведомление менеджера и очистка корзины)
    background_tasks.add_task(
        tg_service.notify_new_order,
        order_details=created_order,
        user_info=user_info
    )
    # <<< Уведомление клиента
    background_tasks.add_task(
        tg_service.notify_customer_order_created,
        customer_tg_id=tg_user_id,
        order_id=order_id,
        order_number=created_order.get("number", str(order_id))
    )
    logger.info(f"Notification and cart clearing tasks for order {order_id} added to background.")

    # 7. Возвращаем данные созданного заказа
    return OrderWooCommerce.model_validate(created_order)



@router.get(
    "/my",
    response_model=List[OrderWooCommerce], # Возвращаем список заказов
    summary="Получить историю своих заказов",
    description="Возвращает список всех заказов, сделанных текущим пользователем Telegram.",
)
async def get_my_orders(
    telegram_data: Annotated[Dict, Depends(validate_telegram_data)],
    wc_service: WooCommerceService = Depends(get_woocommerce_service),
):
    """
    Находит пользователя по Telegram ID, а затем запрашивает все его заказы по customer_id.
    """
    user_info = telegram_data.get('user', {})
    tg_user_id = user_info.get('id')
    logger.info(f"Fetching order history for Telegram user: {tg_user_id}")
    
    # 1. Найти ID пользователя в WooCommerce
    customer_email = f"tg_{tg_user_id}@telegram.user"
    customer = await wc_service.get_customer_by_email(customer_email)

    if not customer or not customer.get('id'):
        logger.warning(f"No WooCommerce customer found for Telegram user {tg_user_id}. Returning empty order list.")
        return [] # Если пользователя нет, то и заказов у него нет

    customer_id = customer['id']

    # 2. Получить все заказы этого пользователя
    try:
        # Запрашиваем все заказы без пагинации (per_page=100 - это максимум по умолчанию)
        # Если заказов может быть больше, нужно будет добавить пагинацию и сюда
        orders_data, _ = await wc_service.get_orders(
            customer_id=customer_id,
            per_page=100, 
            orderby='date', 
            order='desc'
        )
        if orders_data is None:
            return [] # Если сервис вернул None, возвращаем пустой список
        
        logger.info(f"Found {len(orders_data)} orders for customer {customer_id}")
        return orders_data

    except WooCommerceServiceError as e:
        logger.error(f"Failed to fetch orders for customer {customer_id}: {e}")
        raise HTTPException(status_code=e.status_code or 503, detail="Ошибка при получении истории заказов.")
    


@router.get(
    "/{order_id}",
    response_model=OrderWooCommerce,
    summary="Получить детали конкретного заказа",
    description="Возвращает детальную информацию о заказе, если он принадлежит текущему пользователю.",
    responses={
        404: {"description": "Заказ не найден или не принадлежит пользователю"},
        401: {"description": "Ошибка аутентификации Telegram"},
    }
)
async def get_my_order_details(
    order_id: int,
    telegram_data: Annotated[Dict, Depends(validate_telegram_data)],
    wc_service: WooCommerceService = Depends(get_woocommerce_service),
):
    """
    Получает детали заказа по его ID и проверяет, что заказ принадлежит
    аутентифицированному пользователю.
    """
    user_info = telegram_data.get('user', {})
    tg_user_id = user_info.get('id')
    logger.info(f"User {tg_user_id} is requesting details for order {order_id}.")

    # 1. Получаем customer_id текущего пользователя
    # Используем find_or_create, чтобы обработать даже тех, кто еще не делал заказ,
    # хотя вряд ли у них будут заказы для просмотра.
    current_customer_id = await wc_service.find_or_create_customer_by_telegram_data(user_info)
    
    if not current_customer_id:
        # Если не удалось определить пользователя, доступ запрещен
        logger.warning(f"Could not resolve a customer ID for Telegram user {tg_user_id}.")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Не удалось определить пользователя.")

    # 2. Получаем данные запрашиваемого заказа
    try:
        order_details = await wc_service.get_order(order_id)
    except WooCommerceServiceError as e:
        logger.error(f"WooCommerce error fetching order {order_id}: {e}")
        # Если API вернуло ошибку (кроме 404), это внутренняя проблема
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Ошибка при получении данных заказа.")

    # 3. Проверяем, существует ли заказ
    if not order_details:
        logger.warning(f"User {tg_user_id} requested a non-existent order {order_id}.")
        # Возвращаем 404, чтобы не раскрывать информацию
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Заказ не найден.")

    # 4. САМАЯ ВАЖНАЯ ПРОВЕРКА: принадлежит ли заказ этому пользователю
    order_customer_id = order_details.get('customer_id')
    
    logger.debug(f"Verifying ownership for order {order_id}: Requesting user's customer_id is {current_customer_id}, order's customer_id is {order_customer_id}.")

    if order_customer_id != current_customer_id:
        logger.warning(f"ACCESS DENIED: User {tg_user_id} (customer_id: {current_customer_id}) tried to access order {order_id} belonging to customer_id {order_customer_id}.")
        # Снова возвращаем 404 для безопасности
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Заказ не найден.")

    # 5. Если все проверки пройдены, возвращаем данные заказа
    logger.info(f"Successfully verified ownership for order {order_id}. Returning details to user {tg_user_id}.")
    return order_details