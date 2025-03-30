# backend/app/bot/handlers/manager.py
import json
import logging
from typing import Any, Dict, Optional, Tuple, Union
import httpx # Для отправки запросов к API бэкенда
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.utils.markdown import hbold, hlink, hcode

from app.core.config import settings
from app.bot.callback_data import ManagerOrderCallback
from app.bot.keyboards.inline import get_manager_orders_keyboard, get_order_details_keyboard

manager_router = Router(name="manager_handlers")
logger = logging.getLogger(__name__)

# --- Вспомогательная функция для проверки прав менеджера ---
def is_manager(user_id: int) -> bool:
    return user_id in settings.TELEGRAM_MANAGER_IDS

# --- Вспомогательная функция для запросов к API бэкенда ---
# Используем httpx для асинхронных запросов
# В реальном приложении лучше вынести в отдельный сервис/класс
async def api_request(method: str, endpoint: str, params: Optional[Dict] = None, json_data: Optional[Dict] = None) -> Tuple[int, Optional[Any], Optional[httpx.Headers]]:
    """Делает запрос к API бэкенда с добавлением ключа администратора."""
    if not settings.ADMIN_API_KEY:
         logger.error("Admin API key is not set for bot requests.")
         return 503, {"detail": "API key not configured"}, None

    base_url = settings.API_BASE_URL # Например, http://127.0.0.1:8000/api/v1
    full_url = f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}"
    headers = {"X-Admin-API-Key": settings.ADMIN_API_KEY}

    async with httpx.AsyncClient() as client:
        try:
            logger.debug(f"Bot making API request: {method} {full_url} | Params: {params} | JSON: {json_data}")
            response = await client.request(method, full_url, params=params, json=json_data, headers=headers, timeout=20.0)
            logger.debug(f"Bot received API response: {response.status_code}")
            response.raise_for_status() # Вызовет исключение для 4xx/5xx
            # Для успешных запросов без тела (редко)
            if response.status_code == 204:
                return response.status_code, None, response.headers
            # Пытаемся распарсить JSON
            try:
                 return response.status_code, response.json(), response.headers
            except json.JSONDecodeError:
                 logger.error(f"Failed to decode JSON response from API: {response.text[:500]}")
                 return response.status_code, {"detail": "Invalid JSON response from API"}, response.headers
        except httpx.HTTPStatusError as e:
             logger.error(f"API request failed with status {e.response.status_code}: {e.response.text[:500]}")
             error_detail = "Ошибка API бэкенда"
             try: # Пытаемся извлечь detail из ответа бэкенда
                  error_data = e.response.json()
                  error_detail = error_data.get("detail", error_detail)
             except Exception: pass
             return e.response.status_code, {"detail": error_detail}, e.response.headers
        except httpx.RequestError as e:
             logger.error(f"API request connection error: {e}")
             return 503, {"detail": "Ошибка подключения к API бэкенда"}, None
        except Exception as e:
             logger.exception(f"Unexpected error during API request: {e}")
             return 500, {"detail": "Внутренняя ошибка при запросе к API"}, None


# --- Хендлер команды /manager_orders ---
@manager_router.message(Command("manager_orders"))
async def cmd_manager_orders(message: types.Message):
    if not is_manager(message.from_user.id):
        logger.warning(f"Unauthorized access attempt to /manager_orders by user {message.from_user.id}")
        return # Игнорируем или отвечаем сообщением об ошибке

    logger.info(f"Manager {message.from_user.id} requested orders list (page 1).")
    await list_orders(message, page=1) # Вызываем функцию отображения списка

# --- Функция для отображения списка заказов (используется командой и пагинацией) ---
async def list_orders(update: Union[types.Message, types.CallbackQuery], page: int = 1):
    # Определяем, откуда пришел запрос (сообщение или колбэк)
    is_callback = isinstance(update, types.CallbackQuery)
    message = update.message if is_callback else update
    user_id = update.from_user.id

    if not is_manager(user_id): return # Двойная проверка

    # Параметры для API
    params = {"page": page, "per_page": 5, "status": "on-hold,processing"} # 5 заказов на страницу
    status_code, data, headers = await api_request("GET", "/admin/orders/", params=params)

    if status_code == 200 and isinstance(data, list):
        total_pages = int(headers.get("x-wp-totalpages", "1")) if headers else 1
        text = f"{hbold('Активные заказы')} (Страница {page}/{total_pages}):"
        keyboard = get_manager_orders_keyboard(data, page, total_pages)
        if is_callback:
             # Редактируем сообщение, если это колбэк
             try:
                 await message.edit_text(text, reply_markup=keyboard)
             except Exception as e: # Если сообщение не изменилось, может быть ошибка
                  logger.warning(f"Failed to edit message for orders list: {e}")
                  await update.answer() # Просто подтверждаем колбэк
        else:
             # Отправляем новое сообщение, если это команда
             await message.answer(text, reply_markup=keyboard)
    else:
        error_text = data.get("detail", "Не удалось загрузить заказы.") if isinstance(data, dict) else "Неизвестная ошибка API."
        if is_callback:
             await update.answer(f"Ошибка: {error_text}", show_alert=True)
        else:
             await message.answer(f"Ошибка: {error_text}")

# --- Callback Handler для пагинации списка заказов ---
@manager_router.callback_query(ManagerOrderCallback.filter(F.action == "page"))
async def handle_orders_page(query: types.CallbackQuery, callback_data: ManagerOrderCallback):
    if not is_manager(query.from_user.id): return await query.answer("Доступ запрещен.", show_alert=True)

    try:
        page = int(callback_data.value)
        if page < 1: page = 1
        logger.info(f"Manager {query.from_user.id} requested orders list page {page}.")
        await list_orders(query, page=page) # Вызываем функцию отображения списка
    except (ValueError, TypeError):
         logger.error(f"Invalid page value in callback data: {callback_data.value}")
         await query.answer("Некорректный номер страницы.", show_alert=True)
    await query.answer() # Подтверждаем получение колбэка

 # --- Callback Handler для возврата к списку заказов ---
@manager_router.callback_query(ManagerOrderCallback.filter(F.action == "list"))
async def handle_back_to_list(query: types.CallbackQuery, callback_data: ManagerOrderCallback):
    if not is_manager(query.from_user.id): return await query.answer("Доступ запрещен.", show_alert=True)
    logger.info(f"Manager {query.from_user.id} returning to orders list (page 1).")
    await list_orders(query, page=1) # Показываем первую страницу
    await query.answer()

# --- Callback Handler для просмотра деталей заказа ---
@manager_router.callback_query(ManagerOrderCallback.filter(F.action == "details"))
async def handle_order_details(query: types.CallbackQuery, callback_data: ManagerOrderCallback):
    if not is_manager(query.from_user.id): return await query.answer("Доступ запрещен.", show_alert=True)

    order_id = callback_data.order_id
    if not order_id: return await query.answer("Ошибка: ID заказа не найден.", show_alert=True)

    logger.info(f"Manager {query.from_user.id} requested details for order {order_id}.")
    status_code, data, _ = await api_request("GET", f"/admin/orders/{order_id}")

    if status_code == 200 and isinstance(data, dict):
        # Формируем подробное сообщение
        text = format_order_details_for_manager(data) # Нужна функция форматирования
        keyboard = get_order_details_keyboard(order_id, data.get('status', 'unknown'))
        try:
            await query.message.edit_text(text, reply_markup=keyboard, disable_web_page_preview=True)
        except Exception as e:
             logger.warning(f"Failed to edit message for order details {order_id}: {e}")
             # Если редактирование не удалось, отправляем новым сообщением
             await query.message.answer(text, reply_markup=keyboard, disable_web_page_preview=True)

    else:
        error_text = data.get("detail", f"Не удалось загрузить детали заказа {order_id}.") if isinstance(data, dict) else "Неизвестная ошибка API."
        await query.answer(f"Ошибка: {error_text}", show_alert=True)

    await query.answer() # Подтверждаем колбэк

# --- Callback Handler для изменения статуса ---
@manager_router.callback_query(ManagerOrderCallback.filter(F.action == "set_status"))
async def handle_set_status(query: types.CallbackQuery, callback_data: ManagerOrderCallback):
    if not is_manager(query.from_user.id): return await query.answer("Доступ запрещен.", show_alert=True)

    order_id = callback_data.order_id
    new_status = callback_data.value
    if not order_id or not new_status:
        return await query.answer("Ошибка: Неверные данные для смены статуса.", show_alert=True)

    logger.info(f"Manager {query.from_user.id} attempts to set status '{new_status}' for order {order_id}.")
    await query.answer(f"Обновляю статус на '{new_status}'...") # Предварительный ответ

    status_code, data, _ = await api_request("PUT", f"/admin/orders/{order_id}/status", json_data={"status": new_status})

    if status_code == 200 and isinstance(data, dict):
        logger.info(f"Status for order {order_id} successfully updated to '{new_status}' by manager {query.from_user.id}.")
        # Обновляем сообщение с деталями заказа, показывая новый статус
        text = format_order_details_for_manager(data) # Переформатируем с новым статусом
        keyboard = get_order_details_keyboard(order_id, data.get('status', 'unknown'))
        try:
            await query.message.edit_text(text, reply_markup=keyboard, disable_web_page_preview=True)
        except Exception as e:
             logger.warning(f"Failed to edit message after status update for {order_id}: {e}")
             await query.message.reply(f"Статус заказа #{order_id} обновлен на '{new_status}'.") # Отвечаем в чат
        await query.answer(f"Статус обновлен на '{new_status}'!", show_alert=False) # Окончательный ответ
    else:
         error_text = data.get("detail", f"Не удалось обновить статус заказа {order_id}.") if isinstance(data, dict) else "Неизвестная ошибка API."
         await query.answer(f"Ошибка: {error_text}", show_alert=True)


# --- Вспомогательная функция форматирования деталей заказа ---
def format_order_details_for_manager(order: Dict) -> str:
    """Форматирует детали заказа для отправки менеджеру."""
    order_id = order.get('id', 'N/A')
    order_number = order.get('number', order_id)
    status = order.get('status', 'N/A')
    date_created_str = order.get('date_created', 'N/A')
    total = order.get('total', 'N/A')
    currency = order.get('currency_symbol', '$')
    customer_note = order.get('customer_note', '')

    # Клиент
    billing = order.get('billing', {})
    customer_name = f"{billing.get('first_name','')} {billing.get('last_name','')}".strip() or "Не указано"
    customer_phone = billing.get('phone', '')
    customer_email = billing.get('email', '')

    # Ищем Telegram ID и username в метаданных
    tg_user_id = None
    tg_username = None
    tg_first_name = None
    tg_last_name = None
    for meta in order.get('meta_data', []):
        if meta.get('key') == '_telegram_user_id': tg_user_id = meta.get('value')
        if meta.get('key') == '_telegram_username': tg_username = meta.get('value')
        if meta.get('key') == '_telegram_first_name': tg_first_name = meta.get('value')
        if meta.get('key') == '_telegram_last_name': tg_last_name = meta.get('value')

    customer_tg_link = ""
    if tg_user_id:
         tg_name = f"{tg_first_name or ''} {tg_last_name or ''}".strip() or f"ID {tg_user_id}"
         customer_tg_link = f"👤 {hlink(tg_name, f'tg://user?id={tg_user_id}')}"
         if tg_username: customer_tg_link += f" (@{tg_username})"
         customer_tg_link += "\n"

    # Товары
    items_lines = []
    for item in order.get('line_items', []):
        items_lines.append(f"- {item.get('name','?')} ({item.get('quantity','?')} шт.) = {item.get('total','?')}{currency}")
    items_str = "\n".join(items_lines) if items_lines else "Нет данных"

    # Сообщение
    text = f"{hbold(f'Заказ #{order_number}')} (ID: {order_id})\n"
    text += f"Статус: {hcode(status)}\n"
    text += f"Дата: {date_created_str}\n"
    text += "--------------------\n"
    text += f"{hbold('Клиент:')}\n"
    text += customer_tg_link # Ссылка на ТГ
    if customer_name != "Не указано": text += f"Имя (из заказа): {customer_name}\n"
    if customer_phone: text += f"Телефон: {hcode(customer_phone)}\n"
    if customer_email: text += f"Email: {hcode(customer_email)}\n"
    text += "--------------------\n"
    text += f"{hbold('Состав заказа:')}\n{items_str}\n"
    text += "--------------------\n"
    text += f"{hbold('Итого:')} {total}{currency}\n"
    if customer_note:
        text += "--------------------\n"
        text += f"{hbold('Заметка клиента:')}\n{customer_note}\n"

    return text