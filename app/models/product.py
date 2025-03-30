# backend/app/models/product.py
from pydantic import BaseModel
from typing import List, Optional

# Упрощенные модели для начала, можно расширить по необходимости

class Image(BaseModel):
    id: Optional[int] = None
    src: str
    name: Optional[str] = None
    alt: Optional[str] = None

class Category(BaseModel):
    id: int
    name: str
    slug: str

class Product(BaseModel):
    id: int
    name: str
    slug: str
    permalink: str
    status: str
    description: Optional[str] = None
    short_description: Optional[str] = None
    sku: Optional[str] = None
    price: str # Цены часто приходят как строки
    regular_price: str
    sale_price: Optional[str] = None
    on_sale: bool
    stock_quantity: Optional[int] = None
    stock_status: str # 'instock', 'outofstock', 'onbackorder'
    images: List[Image] = []
    categories: List[Category] = []
    # Добавьте другие поля: attributes, variations, meta_data и т.д.