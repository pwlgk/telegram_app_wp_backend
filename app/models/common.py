# backend/app/models/common.py
from pydantic import BaseModel
from typing import Optional, Any

class MetaData(BaseModel):
    """Модель для метаданных WooCommerce."""
    id: Optional[int] = None
    key: str
    value: Any # Значение может быть разного типа