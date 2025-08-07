# backend/app/api/v1/endpoints/admin_orders.py
import logging
from fastapi import APIRouter, Depends, Query, HTTPException, status, Body, BackgroundTasks, Request # Добавили Request
from typing import List, Optional, Dict

from app.services.woocommerce import WooCommerceService, WooCommerceServiceError
from app.services.telegram import TelegramService
from app.dependencies import get_woocommerce_service, get_telegram_service, verify_admin_api_key
from app.models.order import OrderWooCommerce
from app.models.pagination import PaginatedResponse # <<< Импортируем нашу модель
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/admin/orders",
    tags=["Admin Orders"],
    dependencies=[Depends(verify_admin_api_key)]
)

# --- Эндпоинт для получения списка заказов ---
@router.get(
    "/",
    summary="Получить список заказов (для менеджера)",
    response_model=PaginatedResponse[OrderWooCommerce] # <<< Указываем новую модель ответа
)
async def get_admin_orders_list(
    request: Request, # <<< Добавляем зависимость Request
    page: int = Query(1, ge=1),
    per_page: int = Query(10, ge=1, le=50),
    status: Optional[str] = Query(None, description="Фильтр по статусу (или список через запятую: on-hold,processing)"),
    search: Optional[str] = Query(None, description="Поиск по номеру, email..."),
    wc_service: WooCommerceService = Depends(get_woocommerce_service),
):
    """Возвращает пагинированный список заказов для менеджера."""
    status_list = status.split(',') if status else ['on-hold', 'processing']
    try:
        orders_data, headers = await wc_service.get_orders(
            page=page,
            per_page=per_page,
            status=status_list,
            search=search,
            orderby='date',
            order='desc'
        )
        if orders_data is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Заказы не найдены.")

        # --- Логика формирования пагинированного ответа ---
        total_count = 0
        total_pages = 0
        if headers:
            try:
                total_count = int(headers.get('x-wp-total', 0))
                total_pages = int(headers.get('x-wp-totalpages', 0))
            except (ValueError, TypeError):
                logger.warning("Could not parse pagination headers from WooCommerce for admin orders.")
                total_count = len(orders_data)
                total_pages = page

        next_url = None
        if page < total_pages:
            next_url = str(request.url.replace_query_params(page=page + 1))

        previous_url = None
        if page > 1:
            previous_url = str(request.url.replace_query_params(page=page - 1))

        return PaginatedResponse(
            count=total_count,
            next=next_url,
            previous=previous_url,
            results=orders_data
        )

    except WooCommerceServiceError as e:
        raise HTTPException(status_code=e.status_code or 503, detail=e.message)
    except Exception as e:
        logger.exception("Error fetching admin orders list", exc_info=e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Ошибка получения списка заказов.")


# --- Эндпоинт для получения деталей одного заказа ---
@router.get(
    "/{order_id}",
    summary="Получить детали заказа (для менеджера)",
    response_model=OrderWooCommerce
)
async def get_admin_order_details(
    order_id: int,
    wc_service: WooCommerceService = Depends(get_woocommerce_service),
):
    """Возвращает подробную информацию о заказе, включая метаданные."""
    try:
        order = await wc_service.get_order(order_id)
        if order is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Заказ с ID {order_id} не найден.")
        return order
    except WooCommerceServiceError as e:
        raise HTTPException(status_code=e.status_code or 503, detail=e.message)
    except Exception as e:
        logger.exception(f"Error fetching admin order details for ID {order_id}", exc_info=e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Ошибка получения деталей заказа.")


# --- Эндпоинт для обновления статуса заказа ---
class StatusUpdatePayload(BaseModel):
    status: str

@router.put(
    "/{order_id}/status",
    summary="Обновить статус заказа (для менеджера)",
    response_model=OrderWooCommerce
)
async def update_admin_order_status(
    order_id: int,
    payload: StatusUpdatePayload,
    background_tasks: BackgroundTasks,
    wc_service: WooCommerceService = Depends(get_woocommerce_service),
    tg_service: TelegramService = Depends(get_telegram_service),
):
    """Обновляет статус заказа и уведомляет клиента."""
    new_status = payload.status
    logger.info(f"Attempting admin update for order {order_id} to status '{new_status}'")
    try:
        updated_order = await wc_service.update_order_status(order_id, new_status)
        if updated_order is None:
             raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Не удалось обновить статус заказа в WooCommerce.")

        customer_tg_id = None
        for meta in updated_order.get('meta_data', []):
            if meta.get('key') == '_telegram_user_id':
                try:
                    customer_tg_id = int(meta.get('value'))
                    break
                except (ValueError, TypeError):
                    logger.warning(f"Could not parse customer Telegram ID from meta for order {order_id}")

        if customer_tg_id:
            background_tasks.add_task(
                tg_service.notify_customer_status_update,
                customer_tg_id=customer_tg_id,
                order_id=order_id,
                order_number=updated_order.get('number', str(order_id)),
                new_status=new_status
            )
            logger.info(f"Customer notification task for order {order_id} status change added to background.")
        else:
            logger.warning(f"Could not find customer Telegram ID for order {order_id}. Notification skipped.")

        return updated_order

    except WooCommerceServiceError as e:
        raise HTTPException(status_code=e.status_code or 503, detail=e.message)
    except Exception as e:
        logger.exception(f"Unexpected error updating order status for ID {order_id}", exc_info=e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Ошибка обновления статуса заказа.")