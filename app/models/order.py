# backend/app/models/order.py
from pydantic import BaseModel, Field, EmailStr, model_serializer
# EmailStr можно убрать, если email: Optional[str]
from typing import List, Optional, Dict, Any
from app.models.common import MetaData, BillingInfo # <<< ИМПОРТИРУЕМ BillingInfo


class CouponLine(BaseModel): # OK: Модель для строки купона
    code: str

class LineItemCreate(BaseModel): # OK: Модель для строки товара
    product_id: int
    quantity: int = Field(..., gt=0)
    variation_id: Optional[int] = None

    # OK: Сериализатор для пропуска variation_id=None (для Pydantic v2)
    @model_serializer(when_used='json')
    def serialize_skip_null_variation(self):
        data = {'product_id': self.product_id, 'quantity': self.quantity}
        if self.variation_id is not None:
            data['variation_id'] = self.variation_id
        return data

# Модель для СОЗДАНИЯ заказа в WooCommerce
class OrderCreateWooCommerce(BaseModel): # OK: Основная модель для создания
    payment_method: str = "cod"
    payment_method_title: str = "Согласование с менеджером (Telegram)"
    set_paid: bool = False
    status: str = "on-hold"
    billing: Optional[BillingInfo] = None
    shipping: Optional[BillingInfo] = None
    line_items: List[LineItemCreate]
    customer_note: Optional[str] = None
    customer_id: int = 0
    meta_data: List[MetaData] = []
    # >>>>> ДОБАВИТЬ ЭТО ПОЛЕ <<<<<
    coupon_lines: Optional[List[CouponLine]] = None # По умолчанию None
    # >>>>> КОНЕЦ ДОБАВЛЕНИЯ <<<<<

# Модель для ОТВЕТА от WooCommerce
class OrderWooCommerce(BaseModel): # OK: Модель для ответа
    id: int
    parent_id: int
    status: str
    currency: str
    total: str # Итоговая сумма (должна быть с учетом скидки)
    discount_total: str = "0.00" # Общая сумма скидки
    discount_tax: str = "0.00"  # Сумма налога на скидку
    shipping_total: str = "0.00" # Стоимость доставки
    shipping_tax: str = "0.00" # Налог на доставку
    cart_tax: str = "0.00" # Налог корзины
    total_tax: str = "0.00" # Общий налог
    customer_id: int
    order_key: str
    billing: Optional[BillingInfo] = None # OK: Использует обновленную модель
    shipping: Optional[BillingInfo] = None
    payment_method: str
    payment_method_title: str
    transaction_id: Optional[str] = None
    customer_note: Optional[str] = None
    date_created: str
    # Можно сделать более строгую модель для line_items в ответе, если нужно
    line_items: List[Dict]
    tax_lines: List[Dict] = []
    shipping_lines: List[Dict] = []
    fee_lines: List[Dict] = []
    # OK: Добавлено поле для купонов в ответе
    coupon_lines: List[Dict] = [] # В ответе это будет список словарей, а не CouponLine
    meta_data: List[MetaData] = []
    # ... можно добавить _links и другие поля по необходимости
