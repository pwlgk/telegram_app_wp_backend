# backend/app/api/v1/endpoints/categories.py
from fastapi import APIRouter, Depends, Query, HTTPException, status
from typing import List, Optional, Dict

from app.services.woocommerce import WooCommerceService, WooCommerceServiceError
from app.dependencies import get_woocommerce_service
# from app.models.product import Category # Для response_model

# Создаем отдельный роутер для категорий
router = APIRouter()

@router.get(
    "/", # Путь "/" относительно префикса "/categories"
    # response_model=List[Category],
    summary="Получить список категорий",
    description="Получает список категорий товаров из WooCommerce.",
)
async def get_categories_list_endpoint( # Даем другое имя функции для ясности
    parent: Optional[int] = Query(None, description="ID родительской категории"),
    hide_empty: bool = Query(True, description="Скрыть пустые категории"),
    wc_service: WooCommerceService = Depends(get_woocommerce_service),
):
    try:
        categories = await wc_service.get_categories(parent=parent, hide_empty=hide_empty)
        if categories is None:
             raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Категории не найдены.")
        return categories
    except WooCommerceServiceError as e:
        raise HTTPException(status_code=e.status_code or 503, detail=e.message)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Внутренняя ошибка сервера при получении категорий.")