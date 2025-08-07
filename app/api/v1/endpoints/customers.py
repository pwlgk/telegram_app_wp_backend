# backend/app/api/v1/endpoints/customers.py
import logging
from fastapi import APIRouter, Depends, HTTPException, status
from typing import Dict, Annotated, Optional

from app.services.woocommerce import WooCommerceService
from app.dependencies import get_current_customer_id, get_woocommerce_service, validate_telegram_data
from pydantic import BaseModel, Field
from app.models.common import BillingInfo # <<< ИМПОРТИРУЕМ ОБЩУЮ МОДЕЛЬ

logger = logging.getLogger(__name__)
router = APIRouter()


# Модель для обновления данных профиля
class CustomerUpdate(BaseModel):
    first_name: Optional[str] = Field(None, min_length=1)
    last_name: Optional[str] = Field(None, min_length=1)
    billing: Optional[BillingInfo] = None
    
# Модель ответа для данных пользователя
class Customer(BaseModel):
    id: int
    email: str
    first_name: str
    last_name: str
    username: str
    billing: BillingInfo # В ответе всегда будет объект billing

@router.get(
    "/me",
    response_model=Customer,
    summary="Получить данные текущего пользователя",
    # ... (остальные параметры остаются)
)
async def get_current_customer_info(
    telegram_data: Annotated[Dict, Depends(validate_telegram_data)],
    wc_service: WooCommerceService = Depends(get_woocommerce_service),
):
    user_info = telegram_data.get('user', {})
    tg_user_id = user_info.get('id')
    
    # Ищем или создаем пользователя, чтобы гарантировать его существование
    customer_id = await wc_service.find_or_create_customer_by_telegram_data(user_info)

    if not customer_id:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Не удалось обработать профиль пользователя.")

    # Получаем актуальные данные созданного/найденного пользователя
    # Для этого нужен метод get_customer_by_id в сервисе
    customer_data = await wc_service.get_customer_by_id(customer_id) # Предполагаем, что такой метод есть
    if not customer_data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Профиль пользователя не найден.")
        
    return customer_data


@router.put(
    "/me",
    response_model=Customer,
    summary="Обновить данные текущего пользователя",
    description="Обновляет ФИО, телефон и город для текущего пользователя Telegram.",
)
async def update_current_customer_info(
    payload: CustomerUpdate,
    telegram_data: Annotated[Dict, Depends(validate_telegram_data)],
    wc_service: WooCommerceService = Depends(get_woocommerce_service),
):
    user_info = telegram_data.get('user', {})
    customer_id = await wc_service.find_or_create_customer_by_telegram_data(user_info)
    if not customer_id:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Не удалось найти профиль для обновления.")

    # Преобразуем Pydantic модель в словарь, исключая неустановленные значения
    update_data = payload.model_dump(exclude_unset=True)

    if not update_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Не предоставлено данных для обновления.")

    updated_customer = await wc_service.update_customer(customer_id, update_data)
    if not updated_customer:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Не удалось обновить профиль.")
    
    return updated_customer


# в customers.py или новом файле user.py
@router.post("/register", status_code=200)
async def register_user_from_app(
    customer_id: Annotated[int, Depends(get_current_customer_id)]
):
    # Сама зависимость get_current_customer_id уже сделает всю работу.
    # Нам нужно только вернуть подтверждение.
    logger.info(f"User with customer_id {customer_id} confirmed registration via Mini App.")
    return {"status": "ok", "customer_id": customer_id}