# backend/app/services/woocommerce.py
import httpx
import json
import logging
from typing import List, Dict, Optional, Any, Union, Tuple
from pydantic import BaseModel
from httpx import Headers # Импортируем Headers
from app.core.config import settings
# Убедитесь, что модели Product и Category импортированы, если используете их в аннотациях
# from app.models.product import Product, Category
from app.models.order import OrderCreateWooCommerce, OrderWooCommerce

# Настройка логирования
# logging.basicConfig(level=settings.LOGGING_LEVEL.upper()) # Лучше настраивать в main.py
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
        timeouts = httpx.Timeout(10.0, read=20.0, write=10.0, connect=5.0)
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
    ) -> Tuple[Optional[Any], Optional[Headers]]:
        """
        Внутренний метод для выполнения запросов к API с обработкой ошибок.
        Возвращает кортеж (данные_ответа, заголовки_ответа) при успехе или вызывает исключение.
        """
        url = f"{self.base_url.rstrip('/')}/{endpoint.lstrip('/')}"
        payload_dict: Optional[Dict] = None

        if json_data:
            if isinstance(json_data, BaseModel):
                 # Используем exclude_none=True для удаления полей с None (например, coupon_lines)
                 payload_dict = json_data.model_dump(exclude_none=True, by_alias=True)

                 # Фильтрация variation_id: None в line_items
                 if 'line_items' in payload_dict and isinstance(payload_dict['line_items'], list):
                     for item in payload_dict['line_items']:
                         if isinstance(item, dict) and item.get('variation_id') is None:
                             if 'variation_id' in item:
                                 del item['variation_id']

            elif isinstance(json_data, dict):
                 payload_dict = json_data
            else:
                 logger.warning(f"Unsupported json_data type for {method} {endpoint}: {type(json_data)}")
                 payload_dict = {}

        logger.debug(f"Requesting {method} {endpoint} | Params: {params} | Final Payload: {payload_dict!r}")

        try:
            response = await self._client.request(method, endpoint, params=params, json=payload_dict)
            response_headers = response.headers
            response.raise_for_status()

            response_data: Optional[Any] = None
            if response.status_code == 204:
                logger.debug(f"Received 204 No Content for {method} {endpoint}")
                response_data = True
            else:
                content_type = response.headers.get("Content-Type", "")
                if "application/json" in content_type:
                    try:
                        response_data = response.json()
                        logger.debug(f"Received {response.status_code} JSON response for {method} {endpoint}. Body sample: {str(response_data)[:200]}...")
                    except json.JSONDecodeError as json_err:
                         logger.error(f"Failed to decode JSON response for {method} {endpoint}. Status: {response.status_code}. Error: {json_err}. Response text: {response.text[:500]}...")
                         raise WooCommerceServiceError("Ошибка декодирования JSON ответа от WooCommerce", status_code=response.status_code, details=response.text) from json_err
                else:
                     logger.warning(f"Unexpected Content-Type '{content_type}' for {method} {endpoint}. Status: {response.status_code}. Response text: {response.text[:500]}...")
                     response_data = response.text

            return response_data, response_headers

        except httpx.HTTPStatusError as e:
            error_details = e.response.text
            error_status_code = e.response.status_code
            error_message = f"HTTP ошибка {error_status_code} от WooCommerce API"
            wc_error_details = None

            try:
                wc_error = e.response.json()
                error_message = wc_error.get("message", error_message)
                error_code = wc_error.get("code", "unknown_error_code")
                wc_error_details = wc_error.get("data", wc_error)
                logger.error(f"WooCommerce API error: {error_status_code} {error_code} - {error_message} for {e.request.url}")
            except (json.JSONDecodeError, AttributeError):
                 logger.error(f"HTTP error: {error_status_code} for {e.request.url}. Could not parse error response as JSON. Response text: {error_details[:500]}...")

            raise WooCommerceServiceError(
                message=f"Ошибка WooCommerce: {error_message}",
                status_code=error_status_code,
                details=wc_error_details or error_details
            ) from e
        except httpx.TimeoutException as e:
            logger.error(f"Request timeout: {e} for {e.request.url}")
            raise WooCommerceServiceError("Превышен таймаут запроса к WooCommerce API") from e
        except httpx.RequestError as e:
            logger.error(f"Network error: {e} for {e.request.url}")
            raise WooCommerceServiceError("Ошибка сети при подключении к WooCommerce API") from e
        except Exception as e:
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
        # Убрали filter_stock как параметр метода
        **kwargs
    # Возвращаем кортеж (данные, заголовки)
    ) -> Tuple[Optional[List[Dict]], Optional[Headers]]:
        """
        Получает список товаров из WooCommerce и фильтрует по наличию на бэкенде.
        Возвращает кортеж (список_товаров, заголовки).
        """
        params = {
            'page': page, 'per_page': per_page, 'status': status,
            'orderby': orderby, 'order': order, 'category': category,
            'search': search, 'featured': featured, 'on_sale': on_sale,
            **kwargs
        }
        params = {k: v for k, v in params.items() if v is not None}
        logger.info(f"Fetching products from WC with params: {params}")

        try:
            # Получаем данные и заголовки
            response_data, response_headers = await self._request("GET", "products", params=params)

            # >>>>> ФИЛЬТРАЦИЯ ПО НАЛИЧИЮ ДОБАВЛЕНА ЗДЕСЬ <<<<<
            if isinstance(response_data, list):
                original_count = len(response_data)
                # Оставляем товары со статусом 'instock' или 'onbackorder'
                filtered_data = [
                    p for p in response_data
                    if p.get('stock_status') in ('instock', 'onbackorder')
                ]
                filtered_count = len(filtered_data)
                if original_count != filtered_count:
                     logger.info(f"Filtered products by stock status on backend: {filtered_count} out of {original_count} remain.")
                # Возвращаем ОТФИЛЬТРОВАННЫЙ список и ОРИГИНАЛЬНЫЕ заголовки WC
                return filtered_data, response_headers
            elif response_data is None:
                 logger.warning("Received None data from _request for products")
                 return None, response_headers
            else:
                 logger.error(f"Unexpected data type from _request for products: {type(response_data)}. Expected list or None.")
                 return [], response_headers
            # >>>>> КОНЕЦ ФИЛЬТРАЦИИ <<<<<

        except WooCommerceServiceError as e:
             logger.error(f"WooCommerceServiceError in get_products: {e}", exc_info=True)
             raise e
        except Exception as e:
             logger.exception(f"Unexpected error in get_products: {e}")
             raise WooCommerceServiceError("Непредвиденная ошибка при получении товаров") from e


    async def get_product(self, product_id: int) -> Optional[Dict]:
        logger.info(f"Fetching product with ID: {product_id}")
        try:
             data, _ = await self._request("GET", f"products/{product_id}") # Заголовки не нужны
             if isinstance(data, dict):
                 return data
             elif isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
                 logger.warning(f"WC API returned a list for single product ID {product_id}. Using first item.")
                 return data[0]
             else:
                 logger.error(f"Unexpected data type received from WC for product {product_id}: {type(data)}. Data: {data}")
                 return None
        except WooCommerceServiceError as e:
             logger.warning(f"Error fetching product {product_id} from WC: {e}")
             if e.status_code == 404: return None
             raise e
        except Exception as e:
             logger.exception(f"Unexpected error in get_product for ID {product_id}: {e}")
             raise WooCommerceServiceError(f"Непредвиденная ошибка при получении товара {product_id}") from e


    async def get_categories(
        self,
        per_page: int = 100,
        parent: Optional[int] = None,
        orderby: str = 'name',
        order: str = 'asc',
        hide_empty: bool = True,
        **kwargs
    ) -> Optional[List[Dict]]:
        params = {
            'per_page': per_page, 'parent': parent, 'orderby': orderby,
            'order': order, 'hide_empty': hide_empty, **kwargs
        }
        params = {k: v for k, v in params.items() if v is not None}
        logger.info(f"Fetching categories with params: {params}")
        try:
            # Получаем только данные
            response_data, _ = await self._request("GET", "products/categories", params=params)
            if isinstance(response_data, list):
                return response_data
            else:
                 logger.error(f"Unexpected data type received for categories: {type(response_data)}")
                 return []
        except WooCommerceServiceError as e:
             logger.error(f"WooCommerceServiceError in get_categories: {e}", exc_info=True)
             raise e
        except Exception as e:
             logger.exception(f"Unexpected error in get_categories: {e}")
             raise WooCommerceServiceError("Непредвиденная ошибка при получении категорий") from e


    async def get_coupon_by_code(self, code: str) -> Optional[List[Dict]]:
        if not code: return None
        logger.info(f"Fetching coupon with code: {code}")
        params = {'code': code}
        try:
            response_data, _ = await self._request("GET", "coupons", params=params) # Данные, заголовки не нужны
            logger.debug(f"Raw response data from _request for coupon '{code}': {response_data} (Type: {type(response_data)})")
            if isinstance(response_data, list):
                return response_data
            elif response_data is None:
                 logger.warning(f"Received None data from _request for coupon '{code}'")
                 return None
            else:
                 logger.error(f"Unexpected data type received from _request for coupon '{code}': {type(response_data)}. Expected list or None.")
                 return []
        except WooCommerceServiceError as e:
             if e.status_code == 404:
                 logger.info(f"Coupon with code '{code}' not found (404).")
                 return []
             else:
                 logger.error(f"WooCommerceServiceError in get_coupon_by_code for '{code}': {e}", exc_info=True)
                 raise e
        except Exception as e:
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
        payload_dict: Optional[Dict] = None # Определяем переменную
        try:
             # Формируем словарь, убирая поля с None (включая coupon_lines, если он None)
             payload_dict = order_data.model_dump(exclude_none=True, by_alias=True)

             # Явно фильтруем variation_id: None в line_items
             if 'line_items' in payload_dict and isinstance(payload_dict['line_items'], list):
                 for item in payload_dict['line_items']:
                     if isinstance(item, dict) and item.get('variation_id') is None:
                         if 'variation_id' in item:
                             del item['variation_id']

             logger.debug(f"Final payload for POST /orders: {json.dumps(payload_dict, indent=2)}")

             # Передаем СЛОВАРЬ в _request
             created_order_data, _ = await self._request("POST", "orders", json_data=payload_dict) # Используем json_data здесь

             if created_order_data and isinstance(created_order_data, dict):
                 order_id = created_order_data.get('id')
                 logger.info(f"Order created successfully with ID: {order_id}")
                 return created_order_data
             else:
                 logger.error(f"Failed to create order. Received unexpected response type from _request: {type(created_order_data)}")
                 raise WooCommerceServiceError("Не удалось создать заказ: неожиданный ответ от API")

        except WooCommerceServiceError as e:
             logger.error(f"WooCommerce service error during order creation: {e}", exc_info=True)
             raise e
        except Exception as e:
             logger.exception(f"Error preparing or sending order data: {e}")
             raise WooCommerceServiceError("Ошибка при подготовке или отправке данных заказа") from e

    # --- Остальные методы (если есть, например, get_order, get_orders, update_order_status) ---
    # Убедитесь, что они также корректно извлекают данные из кортежа _request
    async def get_order(self, order_id: int) -> Optional[Dict]:
        logger.info(f"Fetching order with ID: {order_id}")
        try:
            data, _ = await self._request("GET", f"orders/{order_id}")
            if isinstance(data, dict): return data
            else: logger.error(f"Unexpected data type for order {order_id}: {type(data)}"); return None
        except WooCommerceServiceError as e:
             logger.warning(f"Error fetching order {order_id} from WC: {e}")
             if e.status_code == 404: return None
             raise e
        except Exception as e:
             logger.exception(f"Unexpected error in get_order for ID {order_id}: {e}")
             raise WooCommerceServiceError(f"Непредвиденная ошибка при получении заказа {order_id}") from e

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

    async def update_order_status(self, order_id: int, new_status: str) -> Optional[Dict]:
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
