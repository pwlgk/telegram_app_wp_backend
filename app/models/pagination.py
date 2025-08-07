# backend/app/models/pagination.py
from pydantic import BaseModel, Field
from typing import List, Optional, TypeVar, Generic

# TypeVar используется для создания дженериков (универсальных типов)
T = TypeVar('T')

class PaginatedResponse(BaseModel, Generic[T]):
    """
    Универсальная модель для пагинированных ответов API.
    """
    count: int = Field(..., description="Total number of items available.")
    next: Optional[str] = Field(None, description="URL to the next page of results.")
    previous: Optional[str] = Field(None, description="URL to the previous page of results.")
    results: List[T] = Field(..., description="The list of items for the current page.")