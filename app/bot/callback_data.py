# backend/app/bot/callback_data.py
from typing import Optional
from aiogram.filters.callback_data import CallbackData

# Используем префикс 'mng' для всех действий менеджера
class ManagerCallback(CallbackData, prefix="mng"):
    """
    Универсальная фабрика для колбэков в панели менеджера.
    `target` - что делаем (orders, customers, ...)
    `action` - какое действие (list, details, page, set_status, ...)
    `order_id` - ID заказа (если применимо)
    `page` - номер страницы (для пагинации)
    `value` - дополнительное значение (например, slug статуса)
    """
    target: str
    action: str
    order_id: Optional[int] = None
    page: Optional[int] = None
    value: Optional[str] = None