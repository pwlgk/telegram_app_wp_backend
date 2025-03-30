# backend/app/bot/callback_data.py
from typing import Optional
from aiogram.filters.callback_data import CallbackData

# Префикс 'mng' для manager actions
class ManagerOrderCallback(CallbackData, prefix="mng_ord"):
    action: str # 'list', 'details', 'set_status', 'page'
    order_id: Optional[int] = None
    value: Optional[str] = None # Для статуса или номера страницы