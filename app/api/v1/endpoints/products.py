# backend/app/api/v1/endpoints/products.py
import logging # Добавляем импорт logging
from fastapi import APIRouter, Depends, Query, HTTPException, status, Response
from typing import List, Optional, Dict
# >>>>> Headers нужно импортировать из httpx или requests, если wc_service их возвращает,
#       но для установки заголовков ответа FastAPI они не нужны напрямую.
#       Убираем импорт starlette.datastructures.Headers, если он не используется в другом месте.
# from starlette.datastructures import Headers
from app.services.woocommerce import WooCommerceService, WooCommerceServiceError
from app.dependencies import get_woocommerce_service
# Импортируем Pydantic модели, если хотим использовать response_model
# from app.models.product import Product

# Создаем логгер для этого модуля
logger = logging.getLogger(__name__)

router = APIRouter()

@router.get(
    "/",
    # response_model=List[Product], # Можно раскомментировать для валидации ответа
    summary="Получить список товаров",
    description="Получает список товаров из WooCommerce с пагинацией, фильтрацией и сортировкой.",
)
async def get_products_list(
    response: Response, # Инъецируем объект Response для установки заголовков
    page: int = Query(1, ge=1, description="Номер страницы"),
    per_page: int = Query(10, ge=1, le=100, description="Количество товаров на странице"),
    category: Optional[str] = Query(None, description="ID или slug категории"),
    search: Optional[str] = Query(None, description="Поисковый запрос"),
    featured: Optional[bool] = Query(None, description="Фильтр по избранным"),
    on_sale: Optional[bool] = Query(None, description="Фильтр по товарам со скидкой"),
    orderby: str = Query('popularity', description="Поле сортировки (date, id, title, price...)"),
    order: str = Query('desc', description="Направление сортировки (asc, desc)"),
    # >>>>> Убираем параметр tag, так как мы убрали его из FilterSidebar <<<<<
    # tag: Optional[str] = Query(None, description="ID метки (тега) для фильтрации"),
    wc_service: WooCommerceService = Depends(get_woocommerce_service),
):
    """
    Возвращает список товаров и устанавливает заголовки пагинации.
    """
    try:
        # Получаем кортеж (список_товаров, заголовки_от_httpx)
        products_data, wc_headers = await wc_service.get_products(
            page=page,
            per_page=per_page,
            category=category,
            search=search,
            featured=featured,
            on_sale=on_sale,
            orderby=orderby,
            order=order,
            # tag=tag, # Убрали передачу тега
        )

        # Проверяем, что список товаров получен
        if products_data is None:
             # Это маловероятно, т.к. сервис должен кидать исключение при ошибке запроса
             logger.warning("WooCommerce service returned None for products data.")
             raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Товары не найдены.")

        # Установка заголовков пагинации в ответ FastAPI
        if wc_headers:
            logger.debug(f"Received headers from WC: {dict(wc_headers)}") # Логируем полученные заголовки
            total_pages = wc_headers.get('x-wp-totalpages')
            total_count = wc_headers.get('x-wp-total')
            link_header = wc_headers.get('link')

            # Устанавливаем заголовки в объект Response FastAPI
            if total_pages:
                logger.info(f"Setting X-WP-TotalPages header: {total_pages}")
                response.headers['X-WP-TotalPages'] = total_pages
            if total_count:
                 logger.info(f"Setting X-WP-Total header: {total_count}")
                 response.headers['X-WP-Total'] = total_count
            if link_header:
                 logger.info(f"Setting Link header: {link_header}")
                 response.headers['Link'] = link_header

            # Добавлять Access-Control-Expose-Headers здесь не нужно и неправильно,
            # это должна делать CORSMiddleware в main.py глобально.
            # Убираем закомментированные строки response.headers.add(...)

        else:
             logger.warning("No headers received from WooCommerceService for products request.")


        # Возвращаем только данные товаров как тело ответа
        return products_data

    except WooCommerceServiceError as e:
        # Ловим ошибку от нашего сервиса (включая ошибки API WooCommerce)
        logger.error(f"WooCommerce service error fetching products: {e}", exc_info=True)
        raise HTTPException(status_code=e.status_code or 503, detail=e.message)
    except Exception as e:
        # Ловим другие непредвиденные ошибки
        logger.exception(f"Unexpected error fetching products list: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Внутренняя ошибка сервера при получении товаров.")


@router.get(
    "/{product_id}", # Позиционный аргумент - путь
    # Дальше - только именованные аргументы:
    # response_model=Product, # Если нужно, раскомментировать
    summary="Получить товар по ID", # summary=...
    description="Получает детальную информацию о конкретном товаре.", # description=...
    # tags=["Products"] # Можно добавить тег, если нужно
)
async def get_product_details(
    product_id: int,
    wc_service: WooCommerceService = Depends(get_woocommerce_service),
):
    try:
        # get_product теперь должен вернуть словарь или None
        product = await wc_service.get_product(product_id)

        if product is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Товар с ID {product_id} не найден.")

        # Возвращаем найденный продукт (словарь)
        return product

    except WooCommerceServiceError as e:
        # Если get_product выбросил ошибку 404 от WC, она будет перехвачена здесь
        logger.warning(f"WooCommerce service error fetching product {product_id}: {e}")
        status_code = e.status_code or 503
        # Проверяем, была ли это ошибка "Not Found"
        # (Зависит от того, какое сообщение об ошибке вы установили в WooCommerceServiceError)
        if status_code == 404 or "not found" in str(e.message).lower():
             raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Товар с ID {product_id} не найден.") from e
        else:
             # Другая ошибка от сервиса/API
             raise HTTPException(status_code=status_code, detail=e.message) from e
    except Exception as e:
        logger.exception(f"Unexpected error fetching product details for ID {product_id}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Внутренняя ошибка сервера при получении товара.")
