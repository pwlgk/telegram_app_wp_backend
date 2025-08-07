# backend/app/api/v1/endpoints/products.py
import logging
from fastapi import APIRouter, Depends, Query, HTTPException, status, Request # Добавили Request
from typing import List, Optional

from app.services.woocommerce import WooCommerceService, WooCommerceServiceError
from app.dependencies import get_woocommerce_service
from app.models.product import Product # Импортируем модель Product для response_model
from app.models.pagination import PaginatedResponse # <<< Импортируем нашу новую модель

# Создаем логгер для этого модуля
logger = logging.getLogger(__name__)

router = APIRouter()

@router.get(
    "/",
    response_model=PaginatedResponse[Product], # <<< Указываем новую модель ответа
    summary="Получить список товаров",
    description="Получает список товаров из WooCommerce с пагинацией, фильтрацией и сортировкой.",
)
async def get_products_list(
    request: Request, # <<< Добавляем зависимость Request
    page: int = Query(1, ge=1, description="Номер страницы"),
    per_page: int = Query(10, ge=1, le=100, description="Количество товаров на странице"),
    category: Optional[str] = Query(None, description="ID или slug категории"),
    search: Optional[str] = Query(None, description="Поисковый запрос"),
    featured: Optional[bool] = Query(None, description="Фильтр по избранным"),
    on_sale: Optional[bool] = Query(None, description="Фильтр по товарам со скидкой"),
    orderby: str = Query('popularity', description="Поле сортировки (date, id, title, price...)"),
    order: str = Query('desc', description="Направление сортировки (asc, desc)"),
    wc_service: WooCommerceService = Depends(get_woocommerce_service),
):
    """
    Возвращает пагинированный список товаров в теле ответа.
    """
    try:
        products_data, wc_headers = await wc_service.get_products(
            page=page,
            per_page=per_page,
            category=category,
            search=search,
            featured=featured,
            on_sale=on_sale,
            orderby=orderby,
            order=order,
        )

        if products_data is None:
             raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Товары не найдены.")

        # --- Логика формирования пагинированного ответа ---
        total_count = 0
        total_pages = 0
        if wc_headers:
            try:
                # Извлекаем общее количество товаров и страниц из заголовков
                total_count = int(wc_headers.get('x-wp-total', 0))
                total_pages = int(wc_headers.get('x-wp-totalpages', 0))
            except (ValueError, TypeError):
                logger.warning("Could not parse pagination headers from WooCommerce.")
                total_count = len(products_data) # В крайнем случае считаем по текущим данным
                total_pages = page

        # Формируем URL для следующей и предыдущей страниц
        next_url = None
        if page < total_pages:
            # request.url.replace_query_params() - удобный способ изменить только один параметр в URL
            next_url = str(request.url.replace_query_params(page=page + 1))

        previous_url = None
        if page > 1:
            previous_url = str(request.url.replace_query_params(page=page - 1))
        
        # Собираем и возвращаем объект PaginatedResponse
        return PaginatedResponse(
            count=total_count,
            next=next_url,
            previous=previous_url,
            results=products_data
        )

    except WooCommerceServiceError as e:
        logger.error(f"WooCommerce service error fetching products: {e}", exc_info=True)
        raise HTTPException(status_code=e.status_code or 503, detail=e.message)
    except Exception as e:
        logger.exception(f"Unexpected error fetching products list: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Внутренняя ошибка сервера при получении товаров.")


@router.get(
    "/{product_id}",
    response_model=Product,
    summary="Получить товар по ID",
    description="Получает детальную информацию о конкретном товаре.",
)
async def get_product_details(
    product_id: int,
    wc_service: WooCommerceService = Depends(get_woocommerce_service),
):
    try:
        product = await wc_service.get_product(product_id)
        if product is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Товар с ID {product_id} не найден.")
        return product
    except WooCommerceServiceError as e:
        logger.warning(f"WooCommerce service error fetching product {product_id}: {e}")
        status_code = e.status_code or 503
        if status_code == 404 or "not found" in str(e.message).lower():
             raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Товар с ID {product_id} не найден.") from e
        else:
             raise HTTPException(status_code=status_code, detail=e.message) from e
    except Exception as e:
        logger.exception(f"Unexpected error fetching product details for ID {product_id}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Внутренняя ошибка сервера при получении товара.")