# backend/app/models/common.py
from pydantic import BaseModel
from typing import Optional, Any

class MetaData(BaseModel):
    """Модель для метаданных WooCommerce."""
    id: Optional[int] = None
    key: str
    value: Any

# >>> ДОБАВЬТЕ ЭТОТ КЛАСС <<<
class BillingInfo(BaseModel):
    """Общая модель для данных биллинга."""
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    city: Optional[str] = None
    # Добавьте другие поля при необходимости (address_1, postcode и т.д.)