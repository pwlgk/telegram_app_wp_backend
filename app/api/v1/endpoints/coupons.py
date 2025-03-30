# backend/app/api/v1/endpoints/coupons.py
import logging
from datetime import datetime, timezone # Убедимся, что оба импортированы
from fastapi import APIRouter, Depends, HTTPException, status, Body
from typing import List, Optional, Dict, Any # Добавили Any для coupon_data
from pydantic import BaseModel

from app.services.woocommerce import WooCommerceService, WooCommerceServiceError
from app.dependencies import get_woocommerce_service

router = APIRouter()
logger = logging.getLogger(__name__)

class CouponValidationRequest(BaseModel):
    code: str
    # Можно добавить subtotal или line_items для более точной проверки
    # subtotal: Optional[float] = None
    # line_items: Optional[List[Dict]] = None # Упрощенно

class CouponValidationResponse(BaseModel):
    valid: bool
    code: str
    message: Optional[str] = None
    discount_type: Optional[str] = None # 'percent', 'fixed_cart', 'fixed_product'
    amount: Optional[str] = None # Сумма скидки (как строка из WC)
    # Можно добавить new_total, если будем считать на бэке

@router.post(
    "/validate",
    response_model=CouponValidationResponse,
    summary="Проверить промокод",
    description="Проверяет существование и базовую валидность купона WooCommerce."
)
async def validate_coupon(
    payload: CouponValidationRequest,
    wc_service: WooCommerceService = Depends(get_woocommerce_service),
):
    coupon_code = payload.code.strip()
    if not coupon_code:
         # Используем status из fastapi
         raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Код купона не может быть пустым.")

    try:
        # wc_service.get_coupon_by_code возвращает Optional[List[Dict]]
        coupons_list: Optional[List[Dict]] = await wc_service.get_coupon_by_code(coupon_code)

        # Проверяем, что список НЕ пустой и содержит хотя бы один элемент
        if not coupons_list: # Если None или []
            logger.info(f"Coupon code '{coupon_code}' not found or invalid by service.")
            return CouponValidationResponse(valid=False, code=coupon_code, message="Промокод не найден или недействителен.")

        # Получаем первый элемент (словарь) из списка
        # Добавляем проверку типа на всякий случай
        if not isinstance(coupons_list[0], dict):
             logger.error(f"Expected a dict for coupon data, but got {type(coupons_list[0])} for code '{coupon_code}'")
             raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Неожиданный формат данных купона.")

        coupon_data: Dict[str, Any] = coupons_list[0]
        logger.debug(f"Coupon data found for code '{coupon_code}': {coupon_data}")

        # --- Базовые проверки (теперь используем coupon_data) ---
        now = datetime.now(timezone.utc)

        # Проверка даты истечения срока действия
        date_expires_str = coupon_data.get('date_expires')
        if date_expires_str:
            try:
                # Преобразуем строку ISO 8601 в объект datetime с учетом таймзоны
                date_expires = datetime.fromisoformat(date_expires_str.replace('Z', '+00:00'))
                if now >= date_expires: # Сравниваем с учетом таймзон
                    logger.info(f"Coupon '{coupon_code}' has expired. Expires at: {date_expires}, Now: {now}")
                    return CouponValidationResponse(valid=False, code=coupon_code, message="Срок действия промокода истек.")
            except (ValueError, TypeError) as date_err:
                 # Логируем ошибку парсинга даты, но не прерываем проверку (может купон валиден без даты)
                 logger.warning(f"Could not parse date_expires for coupon '{coupon_code}': {date_expires_str}. Error: {date_err}")

        # Проверка лимита использования
        # usage_limit - максимальное количество использований купона
        # usage_limit_per_user - максимальное количество использований на пользователя (требует user_id)
        usage_limit = coupon_data.get('usage_limit')
        usage_count = coupon_data.get('usage_count', 0) # Текущее количество использований
        # Проверяем общий лимит
        if usage_limit is not None and usage_count is not None and usage_count >= usage_limit:
             logger.info(f"Coupon '{coupon_code}' usage limit reached. Count: {usage_count}, Limit: {usage_limit}")
             return CouponValidationResponse(valid=False, code=coupon_code, message="Лимит использования промокода исчерпан.")

        # --- Другие возможные проверки (можно добавить по необходимости) ---
        # minimum_amount: "100.00"
        # maximum_amount: "500.00"
        # individual_use: true/false (нельзя использовать с другими купонами)
        # exclude_sale_items: true/false
        # product_ids: [12, 34]
        # excluded_product_ids: [56]
        # product_categories: [1]
        # excluded_product_categories: [2]
        # email_restrictions: ["test@test.com"]
        # -> Для этих проверок нужно передавать больше данных с фронтенда (корзина, email)

        # --- Если базовые проверки пройдены ---
        logger.info(f"Coupon '{coupon_code}' validation successful (basic checks).")
        return CouponValidationResponse(
            valid=True,
            code=coupon_data.get('code', coupon_code), # Возвращаем код
            discount_type=coupon_data.get('discount_type'),
            amount=coupon_data.get('amount'),
            message="Промокод действителен!" # Изменил сообщение
        )

    except WooCommerceServiceError as e:
        # Обработка ошибок от WooCommerceService, кроме 404 (уже обработано выше)
        logger.error(f"WooCommerce error during coupon validation for '{coupon_code}': {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"Ошибка при проверке промокода: {e.message}")
    except IndexError:
        # Если список coupons_list пуст после проверки if not coupons_list (маловероятно, но для надежности)
        logger.error(f"IndexError while accessing coupon data for code '{coupon_code}'. List was likely empty.")
        return CouponValidationResponse(valid=False, code=coupon_code, message="Промокод не найден (ошибка данных).")
    except Exception as e:
         # Ловим все остальные непредвиденные ошибки
         logger.exception(f"Unexpected error validating coupon '{coupon_code}': {e}")
         raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Внутренняя ошибка при проверке промокода.")
