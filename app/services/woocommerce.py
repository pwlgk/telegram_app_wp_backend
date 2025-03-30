# backend/app/services/woocommerce.py
import httpx
import json
import logging
from typing import List, Dict, Optional, Any, Union, Tuple
from pydantic import BaseModel
from httpx import Headers # Убедитесь, что Headers импортирован
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

        # Обработка данных для отправки (json_data)
        if json_data:
            if isinstance(json_data, BaseModel):
                 # Преобразуем Pydantic модель в словарь
                 # Используем exclude_none=True, чтобы убрать поля с None (важно для coupon_lines)
                 payload_dict = json_data.model_dump(exclude_none=True, by_alias=True)

                 # Явная фильтрация variation_id: None в line_items (если нужно)
                 if 'line_items' in payload_dict and isinstance(payload_dict['line_items'], list):
                     for item in payload_dict['line_items']:
                         # Удаляем ключ, только если он есть И его значение None
                         if isinstance(item, dict) and item.get('variation_id') is None:
                             if 'variation_id' in item: # Доп. проверка перед удалением
                                del item['variation_id']

            elif isinstance(json_data, dict):
                 payload_dict = json_data # Используем как есть, если уже словарь
            else:
                 logger.warning(f"Unsupported json_data type for {method} {endpoint}: {type(json_data)}")
                 # Можно решить, что делать - отправить пустой словарь или вызвать ошибку
                 # raise TypeError("Unsupported json_data type")
                 payload_dict = {} # Пока отправляем пустой

        # Логируем окончательный payload перед отправкой
        # Используем repr для payload_dict чтобы избежать проблем с большими данными в логах
        logger.debug(f"Requesting {method} {endpoint} | Params: {params} | Final Payload: {payload_dict!r}")

        try:
            response = await self._client.request(method, endpoint, params=params, json=payload_dict)
            response_headers = response.headers # Сохраняем заголовки
            response.raise_for_status() # Проверяем на HTTP ошибки (4xx, 5xx)

            response_data: Optional[Any] = None
            if response.status_code == 204: # No Content
                logger.debug(f"Received 204 No Content for {method} {endpoint}")
                response_data = True # Используем True как индикатор успеха без тела
            else:
                content_type = response.headers.get("Content-Type", "")
                if "application/json" in content_type:
                    try:
                        response_data = response.json()
                        # Логируем только часть ответа для краткости
                        logger.debug(f"Received {response.status_code} JSON response for {method} {endpoint}. Body sample: {str(response_data)[:200]}...")
                    except json.JSONDecodeError as json_err:
                         logger.error(f"Failed to decode JSON response for {method} {endpoint}. Status: {response.status_code}. Error: {json_err}. Response text: {response.text[:500]}...")
                         # Вызываем ошибку, т.к. ожидали JSON
                         raise WooCommerceServiceError("Ошибка декодирования JSON ответа от WooCommerce", status_code=response.status_code, details=response.text) from json_err
                else:
                     logger.warning(f"Unexpected Content-Type '{content_type}' for {method} {endpoint}. Status: {response.status_code}. Response text: {response.text[:500]}...")
                     response_data = response.text # Возвращаем текст как есть

            # Возвращаем кортеж (данные, заголовки) при успехе
            return response_data, response_headers

        # Обработка ошибок HTTP (уже проверенных raise_for_status)
        except httpx.HTTPStatusError as e:
            error_details = e.response.text
            error_headers = e.response.headers
            error_status_code = e.response.status_code
            error_message = f"HTTP ошибка {error_status_code} от WooCommerce API"
            wc_error_details = None # Детали из JSON ошибки WC

            try:
                wc_error = e.response.json()
                # Используем .get() с дефолтами для безопасности
                error_message = wc_error.get("message", error_message)
                error_code = wc_error.get("code", "unknown_error_code")
                wc_error_details = wc_error.get("data", wc_error) # Сохраняем весь ответ или data
                logger.error(f"WooCommerce API error: {error_status_code} {error_code} - {error_message} for {e.request.url}")
            except (json.JSONDecodeError, AttributeError): # Добавил AttributeError на случай если e.response не имеет .json()
                 logger.error(f"HTTP error: {error_status_code} for {e.request.url}. Could not parse error response as JSON. Response text: {error_details[:500]}...")

            # Всегда вызываем наше исключение
            raise WooCommerceServiceError(
                message=f"Ошибка WooCommerce: {error_message}",
                status_code=error_status_code,
                details=wc_error_details or error_details # Передаем JSON детали или сырой текст
            ) from e

        # Обработка других ошибок httpx
        except httpx.TimeoutException as e:
            logger.error(f"Request timeout: {e} for {e.request.url}")
            raise WooCommerceServiceError("Превышен таймаут запроса к WooCommerce API") from e
        except httpx.RequestError as e:
            logger.error(f"Network error: {e} for {e.request.url}")
            raise WooCommerceServiceError("Ошибка сети при подключении к WooCommerce API") from e
        # Обработка остальных непредвиденных ошибок
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
        # filter_stock: bool = True, # Убрали параметр для передачи в WC
        **kwargs
    # Исправлена аннотация типа возврата
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
        # filter_stock больше не добавляем
        params = {k: v for k, v in params.items() if v is not None}
        logger.info(f"Fetching products from WC with params: {params}")

        try:
            response_data, response_headers = await self._request("GET", "products", params=params)

            # Фильтрация по наличию на бэкенде
            if isinstance(response_data, list):
                original_count = len(response_data)
                filtered_data = [
                    p for p in response_data
                    if p.get('stock_status') in ('instock', 'onbackorder')
                ]
                filtered_count = len(filtered_data)
                if original_count != filtered_count:
                     logger.info(f"Filtered products by stock status on backend: {filtered_count} out of {original_count} remain.")
                return filtered_data, response_headers
            elif response_data is None:
                 logger.warning("Received None data from _request for products")
                 return None, response_headers
            else:
                 logger.error(f"Unexpected data type from _request for products: {type(response_data)}. Expected list or None.")
                 return [], response_headers

        except WooCommerceServiceError as e:
             logger.error(f"WooCommerceServiceError in get_products: {e}", exc_info=True) # Добавил exc_info
             raise e # Пробрасываем ошибку
        except Exception as e:
             logger.exception(f"Unexpected error in get_products: {e}")
             raise WooCommerceServiceError("Непредвиденная ошибка при получении товаров") from e


    async def get_product(self, product_id: int) -> Optional[Dict]:
        logger.info(f"Fetching product with ID: {product_id}")
        try:
            data, _ = await self._request("GET", f"products/{product_id}") # Заголовки не нужны
            if isinstance(data, dict):
                return data
            # ... (обработка list как раньше) ...
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
            # Получаем только данные, заголовки не нужны
            response_data, _ = await self._request("GET", "products/categories", params=params)
            if isinstance(response_data, list):
                return response_data
            else:
                 logger.error(f"Unexpected data type received for categories: {type(response_data)}")
                 return [] # Возвращаем пустой список в случае ошибки типа
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
            # ... (остальная обработка response_data) ...
            elif response_data is None:
                 logger.warning(...)
                 return None
            else:
                 logger.error(...)
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
             # --- ФОРМИРУЕМ СЛОВАРЬ ЗДЕСЬ ---
             # Используем exclude_none=True, чтобы убрать поля с None
             payload_dict = order_data.model_dump(exclude_none=True, by_alias=True)

             # Явно фильтруем variation_id: None в line_items
             if 'line_items' in payload_dict and isinstance(payload_dict['line_items'], list):
                 for item in payload_dict['line_items']:
                     if isinstance(item, dict) and item.get('variation_id') is None:
                         if 'variation_id' in item: # Проверка перед удалением
                             del item['variation_id']

             # Логируем то, что реально будет отправлено
             logger.debug(f"Final payload for POST /orders: {json.dumps(payload_dict, indent=2)}")

             # Передаем СЛОВАРЬ в _request
             created_order_data, _ = await self._request("POST", "orders", json_payload=payload_dict)

             if created_order_data and isinstance(created_order_data, dict):
                 order_id = created_order_data.get('id')
                 logger.info(f"Order created successfully with ID: {order_id}")
                 return created_order_data
             else:
                 # Если _request вернул что-то кроме словаря (например, True или str)
                 logger.error(f"Failed to create order. Received unexpected response type from _request: {type(created_order_data)}")
                 raise WooCommerceServiceError("Не удалось создать заказ: неожиданный ответ от API")

        except WooCommerceServiceError as e:
             # Ошибки, проброшенные из _request
             logger.error(f"WooCommerce service error during order creation: {e}", exc_info=True)
             raise e # Перебрасываем дальше
        except Exception as e:
             # Ошибки дампа или другие непредвиденные
             logger.exception(f"Error preparing or sending order data: {e}")
             raise WooCommerceServiceError("Ошибка при подготовке или отправке данных заказа") from e

    # --- Остальные методы (get_order, get_orders, update_order_status) ---
    # Убедитесь, что они также корректно обрабатывают кортеж от _request,
    # если вы их добавили или будете использовать.
    # Пример для get_order:
    async def get_order(self, order_id: int) -> Optional[Dict]:
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
