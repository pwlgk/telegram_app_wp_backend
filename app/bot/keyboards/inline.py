# backend/app/bot/keyboards/inline.py

from typing import Dict, List
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder
from app.bot.callback_data import ManagerCallback # <<< Импортируем фабрику

from app.core.config import settings

# Этот импорт был в вашем коде, но мы его не использовали в предыдущих шагах.
# Если у вас есть фабрика колбэков ManagerOrderCallback, оставьте его.
# Если нет, и вы используете строки "status:proc:123", то этот импорт не нужен.
# Оставим его закомментированным на случай, если он вам понадобится.
# from app.bot.callback_data import ManagerOrderCallback 

# =============================================================================
# Клавиатуры для обычных пользователей
# =============================================================================

def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    """
    Создает инлайн-клавиатуру с кнопкой для запуска Web App магазина.
    """
    builder = InlineKeyboardBuilder()

    if not settings.MINI_APP_URL_BOT:
        # Логируем предупреждение, если URL не задан
        import logging
        logging.getLogger(__name__).warning("MINI_APP_URL_BOT is not set in settings. Cannot create WebApp button.")
        # Возвращаем кнопку-плейсхолдер
        builder.button(text="❌ Магазин временно недоступен", callback_data="shop_unavailable")
    else:
        # Создаем объект WebAppInfo с URL нашего фронтенда
        web_app_info = WebAppInfo(url=settings.MINI_APP_URL_BOT)

        # Добавляем кнопку типа web_app
        builder.button(
            text="🛍️ Открыть магазин",
            web_app=web_app_info
        )

    # Располагаем кнопку в один ряд
    builder.adjust(1)
    return builder.as_markup()

# =============================================================================
# Клавиатуры для менеджеров
# =============================================================================

def get_admin_order_keyboard(order_id: int, customer_tg_id: int) -> InlineKeyboardMarkup:
    """
    Создает инлайн-клавиатуру для управления заказом в чате менеджера.
    """
    builder = InlineKeyboardBuilder()

    # Кнопки для изменения статуса
    builder.row(
        InlineKeyboardButton(
            text="✅ В работу (Processing)",
            callback_data=f"status:proc:{order_id}"
        ),
        InlineKeyboardButton(
            text="🚀 Выполнен (Completed)",
            callback_data=f"status:comp:{order_id}"
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="❌ Отменить (Cancelled)",
            callback_data=f"status:canc:{order_id}"
        )
    )
    
    # Кнопка для связи с клиентом (прямая ссылка на чат)
    builder.row(
        InlineKeyboardButton(
            text="💬 Написать клиенту",
            url=f"tg://user?id={customer_tg_id}"
        )
    )
    
    return builder.as_markup()

# Словарь для маппинга callback-сокращений в полные статусы и текст для клиента
# Этот словарь будет использоваться в хендлере колбэков.
STATUS_MAP = {
    "proc": {"slug": "processing", "text": "В обработке"},
    "comp": {"slug": "completed", "text": "Выполнен"},
    "canc": {"slug": "cancelled", "text": "Отменен"},
}


def get_manager_orders_keyboard(orders: List[Dict], page: int, total_pages: int, status_slug: str) -> InlineKeyboardMarkup:
    """
    Создает инлайн-клавиатуру со списком заказов и кнопками пагинации.
    """
    builder = InlineKeyboardBuilder()

    # Создаем кнопки для каждого заказа
    for order in orders:
        order_id = order.get('id')
        order_number = order.get('number', order_id)
        total = order.get('total', '?')
        currency = order.get('currency', 'RUB')
        
        builder.button(
            text=f"Заказ №{order_number}  |  {total} {currency}",
            callback_data=ManagerCallback(
                target="orders",
                action="details",
                order_id=order_id,
                page=page, # Сохраняем текущую страницу, чтобы вернуться на нее
                value=status_slug # Сохраняем текущий фильтр статуса
            ).pack()
        )

    # Создаем кнопки пагинации
    pagination_buttons = []
    if page > 1:
        pagination_buttons.append(
            InlineKeyboardButton(
                text="⬅️ Назад",
                callback_data=ManagerCallback(
                    target="orders", action="page", page=page - 1, value=status_slug
                ).pack()
            )
        )
    if total_pages > 1:
         pagination_buttons.append(
            InlineKeyboardButton(
                text=f"{page}/{total_pages}",
                callback_data="do_nothing" # Пустышка, просто для отображения
            )
        )
    if page < total_pages:
        pagination_buttons.append(
            InlineKeyboardButton(
                text="Вперед ➡️",
                callback_data=ManagerCallback(
                    target="orders", action="page", page=page + 1, value=status_slug
                ).pack()
            )
        )
    
    # Добавляем ряд с кнопками пагинации, если они есть
    if pagination_buttons:
        builder.row(*pagination_buttons)

    # Каждый заказ будет на отдельной строке
    builder.adjust(1)
    
    return builder.as_markup()


def get_manager_order_details_keyboard(order: Dict, current_page: int, status_slug: str) -> InlineKeyboardMarkup:
    """
    Создает клавиатуру для управления конкретным заказом.
    """
    builder = InlineKeyboardBuilder()
    order_id = order.get('id')
    current_status = order.get('status')

    # Логика переходов статусов
    status_transitions = {
        'on-hold': [('processing', '✅ В работу'), ('cancelled', '❌ Отменить')],
        'processing': [('completed', '🚀 Выполнен'), ('cancelled', '❌ Отменить')],
        # Для выполненных или отмененных заказов кнопок смены статуса не будет
    }
    
    action_buttons = []
    # Получаем список возможных действий для текущего статуса
    possible_actions = status_transitions.get(current_status, [])
    
    for new_status, text in possible_actions:
        action_buttons.append(
            InlineKeyboardButton(
                text=text,
                callback_data=ManagerCallback(
                    target="orders",
                    action="set_status",
                    order_id=order_id,
                    page=current_page,
                    value=new_status  # В value передаем новый статус
                ).pack()
            )
        )
    
    # Добавляем кнопки смены статуса, если они есть
    if action_buttons:
        builder.row(*action_buttons, width=2) # Располагаем по 2 кнопки в ряд
    customer_tg_id = None
    for meta in order.get('meta_data', []):
        if meta.get('key') == '_telegram_user_id':
            customer_tg_id = int(meta.get('value'))
            break
            
    # Добавляем кнопку "Связаться с клиентом", если мы нашли его ID
    if customer_tg_id:
        builder.row(
            InlineKeyboardButton(
                text="✉️ Связаться с клиентом",
                callback_data=ManagerCallback(
                    target="customer", # Цель - клиент
                    action="contact",  # Действие - связаться
                    order_id=order_id, # Передаем ID заказа для контекста
                    value=str(customer_tg_id) # В value передаем ID клиента
                ).pack()
            )
        )
    # Кнопка "Назад к списку"
    builder.row(
        InlineKeyboardButton(
            text="◀️ Назад к списку",
            callback_data=ManagerCallback(
                target="orders",
                action="page", # Возвращаемся на ту же страницу списка
                page=current_page,
                value=status_slug # С тем же фильтром по статусу
            ).pack()
        )
    )

    return builder.as_markup()

def get_customers_menu_keyboard() -> InlineKeyboardMarkup:
    """Создает меню для раздела 'Клиенты'."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🔎 Поиск клиента",
        callback_data=ManagerCallback(target="customers", action="search_start").pack()
    )
    builder.button(
        text="📋 Список клиентов",
        callback_data=ManagerCallback(target="customers", action="list", page=1).pack()
    )
    builder.button(
        text="🔢 Общее число клиентов",
        callback_data=ManagerCallback(target="customers", action="total").pack()
    )
    builder.adjust(1)
    return builder.as_markup()

def get_customers_pagination_keyboard(page: int, total_pages: int) -> InlineKeyboardMarkup:
    """Создает клавиатуру пагинации для списка клиентов."""
    builder = InlineKeyboardBuilder()
    pagination_buttons = []
    
    if page > 1:
        pagination_buttons.append(
            InlineKeyboardButton(
                text="⬅️ Назад",
                callback_data=ManagerCallback(target="customers", action="page", page=page - 1).pack()
            )
        )
    if total_pages > 1:
        pagination_buttons.append(
            InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="do_nothing")
        )
    if page < total_pages:
        pagination_buttons.append(
            InlineKeyboardButton(
                text="Вперед ➡️",
                callback_data=ManagerCallback(target="customers", action="page", page=page + 1).pack()
            )
        )
        
    if pagination_buttons:
        builder.row(*pagination_buttons)
        
    return builder.as_markup()
def get_stats_menu_keyboard() -> InlineKeyboardMarkup:
    """Создает меню для выбора периода статистики."""
    builder = InlineKeyboardBuilder()
    
    # Кнопки для выбора периода
    builder.button(
        text="📊 За сегодня",
        callback_data=ManagerCallback(target="stats", action="get", value="today").pack()
    )
    builder.button(
        text="📅 За неделю",
        callback_data=ManagerCallback(target="stats", action="get", value="week").pack()
    )
    builder.button(
        text="🗓️ За месяц",
        callback_data=ManagerCallback(target="stats", action="get", value="month").pack()
    )
    
    builder.adjust(1) # Каждая кнопка на новой строке
    return builder.as_markup()


def get_post_order_keyboard(order_id: int) -> InlineKeyboardMarkup:
    """Клавиатура для сообщения клиенту после создания заказа."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="📞 Отправить мой контакт",
        callback_data=f"send_contact:{order_id}"
    )
    return builder.as_markup()

def get_request_contact_from_manager_keyboard(order_id: int) -> InlineKeyboardMarkup: # <<< Добавили order_id
    """
    Создает клавиатуру с кнопкой "Поделиться контактом",
    которая прикрепляется к сообщению от менеджера.
    """
    builder = InlineKeyboardBuilder()
    
    # <<< ИЗМЕНЕНИЕ: Добавляем ID заказа в callback_data
    builder.button(
        text="📞 Поделиться контактом",
        callback_data=f"req_contact_mgr:{order_id}"
    )
    return builder.as_markup()