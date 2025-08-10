# backend/app/api/v1/endpoints/cart.py
import logging
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from typing import List, Dict, Annotated

from app.services.woocommerce import WooCommerceService
# <<< Импортируем новую зависимость
from app.dependencies import get_current_customer_id, get_woocommerce_service
from app.models.order import LineItemCreate

logger = logging.getLogger(__name__)
router = APIRouter()

# Используем префикс с подчеркиванием, чтобы WordPress не показывал это поле в админке по умолчанию
CART_META_KEY = "telegram_cart" 

@router.get(
    "/",
    summary="Получить и синхронизировать корзину пользователя",
    description="Возвращает сохраненную корзину, синхронизированную с актуальными остатками и ценами.",
)
async def get_user_cart(
    background_tasks: BackgroundTasks,
    customer_id: Annotated[int, Depends(get_current_customer_id)],
    wc_service: WooCommerceService = Depends(get_woocommerce_service),
):
    # 1. Получаем полные данные пользователя по его ID
    customer_data = await wc_service.get_customer_by_id(customer_id)
    if not customer_data:
        # Эта ситуация маловероятна, т.к. зависимость уже создала пользователя
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Профиль пользователя не найден.")

    # 2. Получаем сохраненную "грязную" корзину
    saved_cart_items: List[Dict] = []
    for meta_item in customer_data.get("meta_data", []):
        if meta_item.get("key") == CART_META_KEY:
            # API v3 возвращает value как объект, а не строку JSON
            if isinstance(meta_item.get("value"), list):
                saved_cart_items = meta_item["value"]
            break
    
    if not saved_cart_items:
        return {"items": [], "messages": []}

    # 3. Получаем актуальные данные по всем товарам из корзины за один запрос
    product_ids = [item['product_id'] for item in saved_cart_items]
    actual_products_data, _ = await wc_service.get_products(include=product_ids, per_page=100)
    actual_products_map = {prod['id']: prod for prod in actual_products_data} if actual_products_data else {}

    # 4. Синхронизируем корзину
    synced_cart_items = []
    sync_messages = []
    is_changed = False

    for item in saved_cart_items:
        product_id = item['product_id']
        actual_product = actual_products_map.get(product_id)

        if not actual_product or actual_product.get('stock_status') != 'instock':
            product_name = actual_product.get('name') if actual_product else f"Товар #{product_id}"
            sync_messages.append(f"'{product_name}' был удален из корзины, так как он больше не доступен.")
            is_changed = True
            continue

        synced_item = item.copy()
        stock_quantity = actual_product.get('stock_quantity')
        if stock_quantity is not None and item['quantity'] > stock_quantity:
            synced_item['quantity'] = stock_quantity
            sync_messages.append(f"Количество товара '{actual_product.get('name')}' уменьшено до {stock_quantity} шт.")
            is_changed = True
        
        synced_cart_items.append(synced_item)
    
    # 5. Если корзина изменилась, сохраняем ее в фоне
    if is_changed:
        logger.info(f"Cart for customer {customer_id} has changed after sync. Saving new version.")
        cart_to_save = [LineItemCreate.model_validate(i).model_dump(exclude_unset=True) for i in synced_cart_items]
        background_tasks.add_task(
            wc_service.update_customer,
            customer_id=customer_id,
            data_to_update={"meta_data": [{"key": CART_META_KEY, "value": cart_to_save}]}
        )

    # 6. Возвращаем результат
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
    cart_items: List[LineItemCreate],
    customer_id: Annotated[int, Depends(get_current_customer_id)],
    wc_service: WooCommerceService = Depends(get_woocommerce_service),
):
    # --- ИСПРАВЛЕННАЯ ЛОГИКА ---
    # 1. Преобразуем Pydantic модели в словари
    cart_items_dict = [item.model_dump(exclude_unset=True) for item in cart_items]
    
    # 2. Формируем данные для обновления мета-поля
    update_data = {
        "meta_data": [
            {
                "key": CART_META_KEY,
                "value": cart_items_dict
            }
        ]
    }

    # 3. Вызываем сервис для обновления
    logger.info(f"Updating cart for customer {customer_id} with {len(cart_items_dict)} items.")
    updated_customer = await wc_service.update_customer(customer_id, update_data)

    if not updated_customer:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Не удалось сохранить корзину.")

    # Возвращаем исходные данные для подтверждения
    return cart_items