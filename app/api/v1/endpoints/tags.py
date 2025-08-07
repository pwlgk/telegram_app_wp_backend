# backend/app/api/v1/endpoints/tags.py
from fastapi import APIRouter, Depends, Query, HTTPException, status
from typing import List, Optional, Dict
from pydantic import BaseModel # <<< ДОБАВЬТЕ ЭТУ СТРОКУ

from app.services.woocommerce import WooCommerceService, WooCommerceServiceError
from app.dependencies import get_woocommerce_service

# Создаем отдельный роутер для меток
router = APIRouter()

# Можно определить Pydantic модель для метки, если нужна строгая типизация ответа
class ProductTag(BaseModel):
    id: int
    name: str
    slug: str
    description: str
    count: int

@router.get(
    "/",
    response_model=List[ProductTag], # <<< Теперь можно раскомментировать для валидации
    summary="Получить список меток (тегов) товаров",
    description="Получает список всех меток (тегов), используемых в товарах.",
)
async def get_product_tags_endpoint(
    hide_empty: bool = Query(True, description="Скрыть метки, не привязанные к товарам"),
    wc_service: WooCommerceService = Depends(get_woocommerce_service),
):
    try:
        tags = await wc_service.get_product_tags(hide_empty=hide_empty)
        if tags is None:
             raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Метки не найдены.")
        return tags
    except WooCommerceServiceError as e:
        raise HTTPException(status_code=e.status_code or 503, detail=e.message)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Внутренняя ошибка сервера при получении меток.")