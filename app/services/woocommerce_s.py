# backend/app/services/woocommerce.py
import httpx
import json
import logging
from typing import List, Dict, Optional, Any, Union, Tuple
from pydantic import BaseModel
from app.core.config import settings
from app.models.product import Product, Category
from app.models.order import OrderCreateWooCommerce, OrderWooCommerce

# Настройка логирования
logging.basicConfig(level=settings.LOGGING_LEVEL.upper())
logger = logging.getLogger(__name__)

class WooCommerceServiceError(Exception):
    """Базовый класс для ошибок сервиса WooCommerce."""
    def __init__(self, message="Ошибка при взаимодействии с WooCommerce API", status_code=None, details=None):
        self.message = message
        self.status_code = status_code
        self.details = details
        super().__init__(self.message)

class WooCommerceService:
    """
    Асинхронный сервис для взаимодействия с WooCommerce REST API.
    """
    def __init__(self):
        self.base_url = f"{settings.WOOCOMMERCE_URL.rstrip('/')}/wp-json/{settings.WOOCOMMERCE_API_VERSION}"
        self.auth = (settings.WOOCOMMERCE_KEY, settings.WOOCOMMERCE_SECRET)
        # Используем таймауты для предотвращения зависания запросов
        timeouts = httpx.Timeout(10.0, read=20.0, write=10.0, connect=5.0)
        # Используем AsyncClient для переиспользования соединений
        self._client = httpx.AsyncClient(base_url=self.base_url, auth=self.auth, timeout=timeouts)
        logger.info(f"WooCommerceService initialized for URL: {self.base_url}")

    async def close_client(self):
        """Закрывает httpx клиент."""
        if hasattr(self, '_client') and self._client:
            await self._client.aclose()
            logger.info("WooCommerce HTTP client closed.")

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict] = None,
        json_data: Optional[Union[Dict, BaseModel]] = None
    # Возвращаем кортеж: (тело_ответа, заголовки_ответа)
    ) -> Tuple[Optional[Any], Optional[httpx.Headers]]:
        url = f"{self.base_url.rstrip('/')}/{endpoint.lstrip('/')}"
        payload_dict: Optional[Dict] = None

        if json_data:
            if isinstance(json_data, BaseModel):
                 # Преобразуем Pydantic модель в словарь
                 # Используем exclude_unset=True, чтобы убрать все None по умолчанию
                 payload_dict = json_data.model_dump(exclude_unset=True, by_alias=True)
                 # logger.debug(f"Payload from Pydantic model (before filtering variation_id): {payload_dict}") # Опциональный лог

                 # --- ДОПОЛНИТЕЛЬНАЯ ФИЛЬТРАЦИЯ line_items ---
                 # Проходим по line_items и удаляем variation_id, если он None
                 if 'line_items' in payload_dict and isinstance(payload_dict['line_items'], list):
                     for item in payload_dict['line_items']:
                         if isinstance(item, dict) and 'variation_id' in item and item['variation_id'] is None:
                             del item['variation_id']
                 # --- КОНЕЦ ФИЛЬТРАЦИИ ---

            elif isinstance(json_data, dict):
                 payload_dict = json_data # Если уже словарь, используем как есть
            else:
                 logger.warning(f"Unsupported json_data type for {method} {endpoint}: {type(json_data)}")
                 payload_dict = {} # Или вызвать ошибку

        # Логируем окончательный payload
        logger.debug(f"Requesting {method} {endpoint} | Params: {params} | Final Payload: {json.dumps(payload_dict, indent=2)}")

        try:
            response = await self._client.request(method, endpoint, params=params, json=payload_dict)
            response.raise_for_status()

            response_headers = response.headers # <<< СОХРАНЯЕМ ЗАГОЛОВКИ

            if response.status_code == 204:
                logger.debug(...)
                return True, response_headers # <<< ВОЗВРАЩАЕМ КОРТЕЖ

            content_type = response.headers.get("Content-Type", "")
            if "application/json" not in content_type:
                logger.warning(...)
                # Возвращаем текст и заголовки
                return response.text, response_headers # <<< ВОЗВРАЩАЕМ КОРТЕЖ

            response_data = response.json()
            logger.debug(...)
            # Возвращаем JSON и заголовки
            return response_data, response_headers # <<< ВОЗВРАЩАЕМ КОРТЕЖ

        except httpx.HTTPStatusError as e:
            # Ошибка от сервера (4xx, 5xx)
            error_details = e.response.text
            error_headers = e.response.headers if hasattr(e, 'response') else None
            try:
                # Пытаемся извлечь сообщение об ошибке из JSON ответа WC
                wc_error = e.response.json()
                error_message = wc_error.get("message", "No error message in response")
                error_code = wc_error.get("code", "unknown_error_code")
                logger.error(f"WooCommerce API error: {e.response.status_code} {error_code} - {error_message} for {e.request.url}")
                raise WooCommerceServiceError(
                    message=f"Ошибка WooCommerce: {error_message}",
                    status_code=e.response.status_code,
                    details=wc_error
                ) from e
            except (ValueError, KeyError):
                 # Если ответ не JSON или структура другая
                 logger.error(f"HTTP error: {e.response.status_code} for {e.request.url}. Response: {error_details[:500]}...")
                 raise WooCommerceServiceError(
                     message=f"HTTP ошибка {e.response.status_code} от WooCommerce API",
                     status_code=e.response.status_code,
                     details=error_details
                 ) from e

        except httpx.TimeoutException as e:
            logger.error(f"Request timeout: {e} for {e.request.url}")
            raise WooCommerceServiceError("Превышен таймаут запроса к WooCommerce API") from e
        except httpx.RequestError as e:
            # Ошибка сети или соединения
            logger.error(f"Network error: {e} for {e.request.url}")
            raise WooCommerceServiceError("Ошибка сети при подключении к WooCommerce API") from e
        except Exception as e:
             # Другие непредвиденные ошибки
             logger.exception(f"Unexpected error during WooCommerce request to {endpoint}: {e}")
             raise WooCommerceServiceError("Непредвиденная ошибка при работе с WooCommerce API") from e

    # --- Методы для получения данных ---

    async def get_products(
        self,
        page: int = 1,
        per_page: int = 10,
        category: Optional[str] = None,
        search: Optional[str] = None,
        status: str = 'publish',
        featured: Optional[bool] = None,
        on_sale: Optional[bool] = None,
        orderby: str = 'popularity',
        order: str = 'desc',
        **kwargs # Дополнительные параметры API WC
    ) -> Optional[List[Dict]]: # Пока возвращаем Dict для гибкости
        """Получает список товаров из WooCommerce."""
        params = {
            'page': page,
            'per_page': per_page,
            'status': status,
            'orderby': orderby,
            'order': order,
            'category': category,
            'search': search,
            'featured': featured,
            'on_sale': on_sale,
            **kwargs
        }
        
        # Убираем None значения
        params = {k: v for k, v in params.items() if v is not None}

        logger.info(f"Fetching products with params: {params}")
        # _request вернет кортеж (data, headers)
        return await self._request("GET", "products", params=params)

    async def get_product(self, product_id: int) -> Optional[Dict]:
        logger.info(f"Fetching product with ID: {product_id}")
        try:
             # _request возвращает (data, hea
             data, _ = await self._request("GET", f"products/{product_id}")
            # Добавляем проверку, что data - это словарь, а не список
             if isinstance(data, dict):
                 return data # Возвращаем только словарь data
             elif isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
                # Если WC неожиданно вернул список с одним товаром - берем первый
                 logger.warning(f"WooCommerce API returned a list for single product ID {product_id}. Using the first item.")
                 return data[0]
             else:
                 # Если пришел не словарь и не список со словарем
                 logger.error(f"Unexpected data type received from WC for product {product_id}: {type(data)}. Data: {data}")
                 return None # Или вызвать ошибку
        except WooCommerceServiceError as e:
             # Если _request выбросил ошибку (например, 404), пробрасываем ее
             # или можно вернуть None, если 404 - не критическая ошибка для этого метода
             logger.warning(f"Error fetching product {product_id} from WC: {e}")
             if e.status_code == 404:
                 return None # Товар не найден
             raise e # Пробросить другие ошибки сервиса
        except Exception as e:
             logger.exception(f"Unexpected error in get_product for ID {product_id}: {e}")
             raise WooCommerceServiceError(f"Непредвиденная ошибка при получении товара {product_id}") from e

    async def get_categories(
        self,
        per_page: int = 100,
        parent: Optional[int] = None,
        orderby: str = 'name',
        order: str = 'asc',
        hide_empty: bool = True, # Скрывать пустые категории
        **kwargs
    ) -> Optional[List[Dict]]:
        """Получает список категорий товаров."""
        params = {
            'per_page': per_page,
            'parent': parent,
            'orderby': orderby,
            'order': order,
            'hide_empty': hide_empty,
            **kwargs
        }
        params = {k: v for k, v in params.items() if v is not None}
        logger.info(f"Fetching categories with params: {params}")
        return await self._request("GET", "products/categories", params=params)
    
    async def get_order(self, order_id: int) -> Optional[Dict]:
        """Получает детальную информацию о заказе по ID."""
        logger.info(f"Fetching order with ID: {order_id}")
        try:
            data, _ = await self._request("GET", f"orders/{order_id}")
            if isinstance(data, dict):
                return data
            else:
                logger.error(f"Unexpected data type received from WC for order {order_id}: {type(data)}")
                return None
        except WooCommerceServiceError as e:
             logger.warning(f"Error fetching order {order_id} from WC: {e}")
             if e.status_code == 404: return None
             raise e
        except Exception as e:
             logger.exception(f"Unexpected error in get_order for ID {order_id}: {e}")
             raise WooCommerceServiceError(f"Непредвиденная ошибка при получении заказа {order_id}") from e

    # --- НОВЫЙ Метод get_orders (получение списка заказов) ---
    async def get_orders(
        self,
        page: int = 1,
        per_page: int = 10,
        status: Optional[Union[str, List[str]]] = None, # Статус или список статусов
        customer_id: Optional[int] = None, # Для поиска по ID клиента WP (не TG ID)
        search: Optional[str] = None, # Поиск по номеру, email и т.д.
        orderby: str = 'date',
        order: str = 'desc',
        **kwargs
    ) -> Tuple[Optional[List[Dict]], Optional[httpx.Headers]]:
        """Получает список заказов из WooCommerce."""
        params = {
            'page': page,
            'per_page': per_page,
            'orderby': orderby,
            'order': order,
            'customer': customer_id,
            'search': search,
            **kwargs # Доп. параметры, если нужны (например, dates)
        }
        # Обработка статуса (может быть строкой 'any' или списком)
        if isinstance(status, list):
            params['status'] = ','.join(status) # WC принимает статусы через запятую
        elif isinstance(status, str) and status != 'any': # 'any' - по умолчанию, если None
             params['status'] = status

        params = {k: v for k, v in params.items() if v is not None}
        logger.info(f"Fetching orders with params: {params}")
        # Возвращаем данные и заголовки для пагинации
        return await self._request("GET", "orders", params=params)

    # --- НОВЫЙ Метод update_order_status ---
    async def update_order_status(self, order_id: int, new_status: str) -> Optional[Dict]:
        """Обновляет статус заказа в WooCommerce."""
        payload = {"status": new_status}
        logger.info(f"Attempting to update status for order ID {order_id} to '{new_status}'")
        try:
            # Используем PUT или POST, WC API v3 поддерживает PUT для обновления
            # Возвращаем только данные обновленного заказа
            updated_order_data, _ = await self._request("PUT", f"orders/{order_id}", json_data=payload)

            if updated_order_data and isinstance(updated_order_data, dict):
                 logger.info(f"Order ID {order_id} status updated successfully to '{new_status}'")
                 return updated_order_data
            else:
                 logger.error(f"Failed to update order status for {order_id}. Received unexpected response: {updated_order_data}")
                 raise WooCommerceServiceError(f"Не удалось обновить статус заказа {order_id} или получен некорректный ответ")
        except WooCommerceServiceError as e:
            logger.error(f"WooCommerce service error updating order status for {order_id}: {e}", exc_info=True)
            raise # Перебрасываем ошибку
        except Exception as e:
             logger.exception(f"Unexpected error in update_order_status for ID {order_id}: {e}")
             raise WooCommerceServiceError(f"Непредвиденная ошибка при обновлении статуса заказа {order_id}") from e

# В services/woocommerce.py
    async def get_coupon_by_code(self, code: str) -> Optional[List[Dict]]:
        if not code:
            return None
        logger.info(f"Fetching coupon with code: {code}")
        params = {'code': code}
        try:
            # Ожидаем кортеж (данные, заголовки) от _request
            response_data, response_headers = await self._request("GET", "coupons", params=params)

            logger.debug(f"Raw response data from _request for coupon '{code}': {response_data} (Type: {type(response_data)})")
            logger.debug(f"Response headers: {response_headers}")

            # Проверяем ТИП полученных ДАННЫХ (response_data)
            if isinstance(response_data, list):
                return response_data # Возвращаем список, если это список
            elif response_data is None:
                logger.warning(f"Received None data from _request for coupon '{code}' (Request might have failed silently in _request if exception handling changed)")
                return None
            else:
                # Если _request вернул что-то неожиданное (True, str?)
                logger.error(f"Unexpected data type received from _request for coupon '{code}': {type(response_data)}. Expected list or None.")
                # Возвращаем пустой список, чтобы не ломать coupons.py
                return []

        except WooCommerceServiceError as e:
            # Обработка ошибок, которые пробросил _request
            if e.status_code == 404:
                logger.info(f"Coupon with code '{code}' not found (404).")
                return [] # Возвращаем пустой список
            else:
                # Пробрасываем другие ошибки сервиса дальше
                logger.error(f"WooCommerceServiceError in get_coupon_by_code for '{code}': {e}")
                raise e # Пробрасываем ошибку
        except Exception as e:
            # Ловим непредвиденные ошибки уже в этом методе
            logger.exception(f"Unexpected error in get_coupon_by_code for '{code}': {e}")
            raise WooCommerceServiceError(f"Непредвиденная ошибка при получении купона {code}") from e


    # --- Метод для создания заказа ---

    async def create_order(self, order_data: OrderCreateWooCommerce) -> Optional[Dict]:
        """
        Создает новый заказ в WooCommerce.
        :param order_data: Pydantic модель OrderCreateWooCommerce с данными заказа.
        :return: Словарь с данными созданного заказа или пробрасывает WooCommerceServiceError.
        """
        logger.info(f"Attempting to create order...")

        # Передаем Pydantic модель в _request, он сам ее обработает и отфильтрует variation_id
        created_order_data, _ = await self._request("POST", "orders", json_data=order_data)

        if created_order_data and isinstance(created_order_data, dict):
            order_id = created_order_data.get('id')
            logger.info(f"Order created successfully with ID: {order_id}")
            return created_order_data
        else:
            logger.error(f"Failed to create order. Received unexpected response: {created_order_data}")
            raise WooCommerceServiceError(
                "Не удалось создать заказ или получен некорректный ответ от WooCommerce",
                details=created_order_data
            )
