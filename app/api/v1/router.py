# backend/app/api/v1/router.py
from fastapi import APIRouter
# Импортируем все роутеры эндпоинтов
from app.api.v1.endpoints import products, orders, categories, coupons, tags, customers,cart # <<< ДОБАВЛЯЕМ customers
from app.api.v1.endpoints import admin_orders

api_router_v1 = APIRouter()

# Подключаем роутеры из эндпоинтов с префиксами
api_router_v1.include_router(products.router, prefix="/products", tags=["Products"])
api_router_v1.include_router(orders.router, prefix="/orders", tags=["Orders"])
# >>>>> ДОБАВЛЯЕМ ПОДКЛЮЧЕНИЕ РОУТЕРА КАТЕГОРИЙ <<<<<
api_router_v1.include_router(categories.router, prefix="/categories", tags=["Categories"])
api_router_v1.include_router(admin_orders.router)
api_router_v1.include_router(coupons.router, prefix="/coupons", tags=["Coupons"])
api_router_v1.include_router(tags.router, prefix="/tags", tags=["Tags"]) # <<< ДОБАВЛЯЕМ ЭТУ СТРОКУ
api_router_v1.include_router(customers.router, prefix="/customers", tags=["Customers"]) # <<< ДОБАВЛЯЕМ ЭТУ СТРОКУ
api_router_v1.include_router(cart.router, prefix="/cart", tags=["Cart"]) # <<< ДОБАВЛЯЕМ ЭТУ СТРОКУ

