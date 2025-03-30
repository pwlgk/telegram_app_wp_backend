# backend/app/bot/keyboards/inline.py
from typing import Dict, List
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder
from app.bot.callback_data import ManagerOrderCallback
from app.core.config import settings

def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    """
    Создает инлайн-клавиатуру с кнопкой для запуска Web App магазина.
    """
    # Используем InlineKeyboardBuilder для удобного создания клавиатур
    builder = InlineKeyboardBuilder()

    # Проверяем, что URL для Mini App задан в настройках
    if not settings.MINI_APP_URL:
        # В этом случае не можем создать кнопку WebApp.
        # Можно вернуть пустую клавиатуру или кнопку с сообщением об ошибке.
        # Логируем предупреждение.
        import logging
        logging.getLogger(__name__).warning("MINI_APP_URL is not set in settings. Cannot create WebApp button.")
        # Вернем простую кнопку как плейсхолдер или можно вообще ничего не возвращать
        builder.button(text="❌ Магазин временно недоступен", callback_data="shop_unavailable")
    else:
        # Создаем объект WebAppInfo с URL нашего фронтенда
        web_app_info = WebAppInfo(url=settings.MINI_APP_URL)

        # Добавляем кнопку типа web_app
        builder.button(
            text="🛍️ Открыть магазин", # Текст на кнопке
            web_app=web_app_info
        )

    # Указываем, что кнопки должны располагаться по одной в строке
    builder.adjust(1)

    # Возвращаем готовую клавиатуру
    return builder.as_markup()

# Пример другой клавиатуры, если понадобится
# def get_some_other_keyboard() -> InlineKeyboardMarkup:
#     builder = InlineKeyboardBuilder()
#     builder.button(text="Кнопка 1", callback_data="button_1_pressed")
#     builder.button(text="Кнопка 2", callback_data="button_2_pressed")
#     builder.adjust(2) # Две кнопки в строке
#     return builder.as_markup()

def get_manager_orders_keyboard(orders: List[Dict], current_page: int, total_pages: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if not orders:
        builder.button(text="Нет заказов для отображения", callback_data="mng_no_orders")
    else:
        for order in orders:
            order_id = order.get('id')
            customer_name = order.get('billing', {}).get('first_name', 'Клиент') # Простое имя
            total = order.get('total', '?')
            currency = order.get('currency_symbol', '$')
            status = order.get('status', '?')
            builder.button(
                text=f"#{order_id} ({customer_name}) - {total}{currency} [{status}]",
                callback_data=ManagerOrderCallback(action="details", order_id=order_id).pack()
            )

    # Пагинация
    row_buttons = []
    if current_page > 1:
        row_buttons.append(InlineKeyboardButton(
            text="⬅️ Назад",
            callback_data=ManagerOrderCallback(action="page", value=str(current_page - 1)).pack()
        ))
    if orders and current_page < total_pages: # Показываем "Вперед", только если есть товары и не последняя страница
         row_buttons.append(InlineKeyboardButton(
             text="Вперед ➡️",
             callback_data=ManagerOrderCallback(action="page", value=str(current_page + 1)).pack()
         ))
    if row_buttons:
         builder.row(*row_buttons) # Добавляем кнопки пагинации в один ряд

    builder.adjust(1) # Каждый заказ на новой строке
    return builder.as_markup()

# Клавиатура для деталей заказа с кнопками статусов
def get_order_details_keyboard(order_id: int, current_status: str) -> InlineKeyboardMarkup:
     builder = InlineKeyboardBuilder()
     # Определяем возможные следующие статусы
     possible_statuses = {
         'on-hold': [('processing', 'В обработку'), ('cancelled', 'Отменить')],
         'processing': [('completed', 'Выполнен'), ('cancelled', 'Отменить')],
         # Добавьте другие переходы по необходимости
     }
     # Статусы, которые можно установить всегда (или из любого состояния)
     always_possible = [('on-hold', 'На удержание')]

     available_actions = possible_statuses.get(current_status, []) + always_possible

     status_buttons = []
     for status_key, status_text in available_actions:
         if status_key != current_status: # Не показываем кнопку для текущего статуса
             status_buttons.append(
                 InlineKeyboardButton(
                     text=f"➡️ {status_text}",
                     callback_data=ManagerOrderCallback(
                         action="set_status",
                         order_id=order_id,
                         value=status_key
                     ).pack()
                 )
             )

     if status_buttons:
         builder.row(*status_buttons, width=1) # Кнопки статусов по одной в ряд

     # Кнопка Назад к списку (опционально)
     builder.row(InlineKeyboardButton(
         text="⬅️ К списку заказов",
         callback_data=ManagerOrderCallback(action="list").pack() # Просто вернемся к списку (на 1ю стр)
     ))
     return builder.as_markup()