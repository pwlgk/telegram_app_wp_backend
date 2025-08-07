# backend/app/api/v1/endpoints/cart.py
import logging
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from typing import List, Dict, Annotated, Optional

from app.services.woocommerce import WooCommerceService
from app.dependencies import get_woocommerce_service, validate_telegram_data
from app.models.order import LineItemCreate # Переиспользуем модель товара в корзине

logger = logging.getLogger(__name__)
router = APIRouter()

CART_META_KEY = "telegram_cart" 

@router.get(
    "/",
    # response_model теперь должен быть более сложным, чтобы передавать доп. информацию
    # Пока оставим его гибким, возвращая Dict, или создадим новую модель
    summary="Получить и синхронизировать корзину пользователя",
    description="Возвращает сохраненную корзину, синхронизированную с актуальными остатками и ценами.",
)
async def get_user_cart(
    background_tasks: BackgroundTasks, # <<< Добавляем для фонового сохранения
    telegram_data: Annotated[Dict, Depends(validate_telegram_data)],
    wc_service: WooCommerceService = Depends(get_woocommerce_service),
):
    user_info = telegram_data.get('user', {})
    customer_id = await wc_service.find_or_create_customer_by_telegram_data(user_info)
    if not customer_id:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Не удалось обработать профиль пользователя.")

    customer_data = await wc_service.get_customer_by_id(customer_id)
    if not customer_data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Профиль пользователя не найден.")

    # 1. Получаем сохраненную "грязную" корзину
    saved_cart_items: List[Dict] = []
    for meta_item in customer_data.get("meta_data", []):
        if meta_item.get("key") == CART_META_KEY:
            if isinstance(meta_item.get("value"), list):
                saved_cart_items = meta_item["value"]
                break
    
    if not saved_cart_items:
        return {"items": [], "messages": []} # Возвращаем пустую корзину

    # 2. Получаем актуальные данные по всем товарам из корзины за один запрос
    product_ids = [item['product_id'] for item in saved_cart_items]
    
    # Запрашиваем данные по ID, per_page=100 чтобы получить все за раз
    actual_products_data, _ = await wc_service.get_products(include=product_ids, per_page=100)
    
    # Преобразуем список товаров в словарь для быстрого доступа по ID
    actual_products_map = {prod['id']: prod for prod in actual_products_data} if actual_products_data else {}

    # 3. Синхронизируем корзину
    synced_cart_items = []
    sync_messages = [] # Сообщения для пользователя (например, "Товар X удален")
    is_changed = False # Флаг, что корзина изменилась и ее надо пересохранить

    for item in saved_cart_items:
        product_id = item['product_id']
        actual_product = actual_products_map.get(product_id)

        # Случай 1: Товар больше не существует или не в статусе 'publish'
        if not actual_product:
            sync_messages.append(f"Товар с ID {product_id} был удален из корзины, так как он больше не доступен.")
            is_changed = True
            continue # Пропускаем этот товар

        # Случай 2: Товар не в наличии
        if actual_product.get('stock_status') != 'instock':
            sync_messages.append(f"Товар '{actual_product.get('name')}' был удален из корзины, так как он закончился.")
            is_changed = True
            continue # Пропускаем этот товар

        synced_item = item.copy()

        # Случай 3: Количество в корзине превышает остаток на складе
        stock_quantity = actual_product.get('stock_quantity')
        if stock_quantity is not None and item['quantity'] > stock_quantity:
            synced_item['quantity'] = stock_quantity
            sync_messages.append(f"Количество товара '{actual_product.get('name')}' уменьшено до {stock_quantity} шт. (максимально доступно).")
            is_changed = True

        # Здесь можно добавить обновление цен, названий и т.д., если нужно
        # synced_item['price'] = actual_product.get('price')
        
        synced_cart_items.append(synced_item)
    
    # 4. (Опционально) Если корзина изменилась, сохраняем ее в фоне
    if is_changed:
        logger.info(f"Cart for customer {customer_id} has changed after sync. Saving new version.")
        cart_to_save = [LineItemCreate.model_validate(i).model_dump(exclude_unset=True) for i in synced_cart_items]
        background_tasks.add_task(
            wc_service.update_customer,
            customer_id=customer_id,
            data_to_update={"meta_data": [{"key": CART_META_KEY, "value": cart_to_save}]}
        )

    # 5. Возвращаем синхронизированную корзину и сообщения для пользователя
    # Оборачиваем ответ в объект, чтобы фронтенд мог показать сообщения
    return {
        "items": synced_cart_items,
        "messages": sync_messages
    }


@router.post(
    "/",
    response_model=List[LineItemCreate],
    summary="Сохранить/обновить корзину пользователя",
    description="Полностью перезаписывает корзину пользователя новыми данными. Для очистки корзины передайте пустой массив [].",
)
async def update_user_cart(
    cart_items: List[LineItemCreate], # Принимаем полный список товаров в корзине
    telegram_data: Annotated[Dict, Depends(validate_telegram_data)],
    wc_service: WooCommerceService = Depends(get_woocommerce_service),
):
    user_info = telegram_data.get('user', {})
    customer_id = await wc_service.find_or_create_customer_by_telegram_data(user_info)
    if not customer_id:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Не удалось найти профиль для сохранения корзины.")

    # Преобразуем список Pydantic моделей в список словарей для сохранения в JSON
    cart_items_dict = [item.model_dump(exclude_unset=True) for item in cart_items]
    
    # Формируем данные для обновления мета-поля
    update_data = {
        "meta_data": [
            {
                "key": CART_META_KEY,
                "value": cart_items_dict
            }
        ]
    }

    logger.info(f"Updating cart for customer {customer_id} with {len(cart_items_dict)} items.")
    updated_customer = await wc_service.update_customer(customer_id, update_data)

    if not updated_customer:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Не удалось сохранить корзину.")

    # Возвращаем сохраненные данные для подтверждения
    return cart_items