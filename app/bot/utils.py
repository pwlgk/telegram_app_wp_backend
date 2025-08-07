# backend/app/bot/utils.py
import logging
from typing import Dict
from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeDefault
from aiogram.utils.markdown import hbold, hlink, hcode

# <<< ПРАВИЛЬНЫЙ ИМПОРТ ДЛЯ СОВРЕМЕННОГО AIOGRAM >>>
import html

logger = logging.getLogger(__name__)
html_escape = html.escape
# --- Вспомогательная функция для установки команд ---
async def set_bot_commands(bot: Bot):
    """Устанавливает список команд, видимых пользователям в меню."""
    commands = [
        BotCommand(command="start", description="🚀 Перезапустить / Начать"),
        BotCommand(command="shop", description="🛍️ Открыть магазин"), # <<< НОВАЯ КОМАНДА
        BotCommand(command="myorders", description="📦 Мои заказы"),
    ]
    try:
        await bot.set_my_commands(commands, scope=BotCommandScopeDefault())
        logger.info("Bot commands have been set successfully.")
    except Exception as e:
        logger.error(f"Failed to set bot commands: {e}")

# --- Функция форматирования данных о клиенте ---
def format_customer_info(user_info: dict, billing_info: dict = None) -> str:
    """
    Форматирует блок информации о клиенте с несколькими способами связи.
    """
    tg_user_id = user_info.get('id')
    tg_username = user_info.get('username')
    
    # <<< ИСПОЛЬЗУЕМ ВСТРОЕННУЮ БИБЛИОТЕКУ HTML ДЛЯ ЭКРАНИРОВАНИЯ >>>
    # Это самый надежный способ, не зависящий от изменений в aiogram.
    # Получаем значения, которые могут быть None
    first_name_val = user_info.get('first_name')
    last_name_val = user_info.get('last_name')

    # Гарантируем, что мы передаем строку в html.escape, а не None
    tg_first_name = html.escape(first_name_val or '')
    tg_last_name = html.escape(last_name_val or '')
    
    # Имя: приоритет отдаем данным из Telegram
    full_name = f"{tg_first_name} {tg_last_name}".strip()
    if not full_name:
        full_name = "Имя не указано"
        
    lines = [hbold(full_name)]

    # 1. Прямая ссылка (самый надежный способ)
    lines.append(f"• Профиль TG: {hlink('Открыть', f'tg://user?id={tg_user_id}')}")
    
    # 2. Юзернейм (если есть)
    if tg_username:
        lines.append(f"• Юзернейм: @{tg_username}")
    
    # 3. Данные из заказа/профиля WP
    if billing_info:
        phone = billing_info.get('phone')
        email = billing_info.get('email')
        if phone:
            lines.append(f"• Телефон: {hcode(phone)}")
        if email and '@telegram.user' not in email:
            lines.append(f"• Email: {hcode(email)}")

    return "\n".join(lines)


async def format_order_details(order: Dict, bot: Bot) -> str:
    """
    Форматирует детальную информацию о заказе для отправки менеджеру.
    Асинхронно запрашивает актуальное имя пользователя в Telegram.
    """
    order_id = order.get('id', 'N/A')
    order_number = order.get('number', order_id)
    status = order.get('status', 'N/A')
    total = order.get('total', 'N/A')
    currency = order.get('currency', '')
    customer_note = html.escape(order.get('customer_note', ''))

    # --- УЛУЧШЕННЫЙ БЛОК ПОЛУЧЕНИЯ ДАННЫХ О КЛИЕНТЕ ---
    customer_block = "Клиент не указан"
    billing_info = order.get('billing', {})
    
    telegram_user_id = None
    for meta in order.get('meta_data', []):
        if meta.get('key') == '_telegram_user_id':
            try:
                telegram_user_id = int(meta.get('value'))
                break
            except (ValueError, TypeError):
                pass

    if telegram_user_id:
        user_info_for_formatter = {'id': telegram_user_id}
        
        # Шаг 1: Попытка получить актуальные данные из Telegram
        try:
            logger.debug(f"Attempting to get_chat for user_id: {telegram_user_id}")
            chat = await bot.get_chat(chat_id=telegram_user_id)
            logger.debug(f"get_chat response for {telegram_user_id}: {chat.model_dump_json(indent=2)}")
            
            # Собираем данные из ответа Telegram
            user_info_for_formatter['first_name'] = chat.first_name
            user_info_for_formatter['last_name'] = chat.last_name
            user_info_for_formatter['username'] = chat.username
            
        except Exception as e:
            logger.warning(f"Could not fetch chat info for user {telegram_user_id}: {e}. Falling back to stored data.")
            # Если не удалось, ищем сохраненные данные в мета-полях заказа
            for meta in order.get('meta_data', []):
                if meta.get('key') == '_telegram_username':
                    user_info_for_formatter['username'] = meta.get('value')
                # Можно также сохранять first/last name в мета-поля заказа при создании
                # if meta.get('key') == '_telegram_first_name':
                #     user_info_for_formatter['first_name'] = meta.get('value')
        
        # Шаг 2: Если имя из Telegram все еще не получено, берем его из биллинга
        current_name = f"{user_info_for_formatter.get('first_name', '')} {user_info_for_formatter.get('last_name', '')}".strip()
        if not current_name and billing_info.get('first_name'):
             logger.debug(f"User name from Telegram is empty, using name from billing info: {billing_info.get('first_name')}")
             user_info_for_formatter['first_name'] = billing_info.get('first_name')
             user_info_for_formatter['last_name'] = billing_info.get('last_name', '')

        customer_block = format_customer_info(user_info_for_formatter, billing_info)
    else:
        # Если в заказе вообще нет ID, показываем данные из биллинга
        name = f"{billing_info.get('first_name', '')} {billing_info.get('last_name', '')}".strip()
        phone = billing_info.get('phone', '')
        customer_block = hbold(name or "Имя не указано")
        if phone:
            customer_block += f"\n• Телефон: {hcode(phone)}"
    # --- КОНЕЦ УЛУЧШЕННОГО БЛОКА ---

    # Формируем список товаров
    items_list = []
    for item in order.get('line_items', []):
        name = html.escape(item.get('name', 'Неизвестный товар'))
        quantity = item.get('quantity', 0)
        item_total = item.get('total', '0')
        items_list.append(f" • {name} ({quantity} шт.) - {hbold(f'{item_total} {currency}')}")
    items_str = "\n".join(items_list) if items_list else "Состав заказа пуст."

    # Собираем финальное сообщение
    text = (
        f"📦 {hbold(f'Детали заказа №{order_number}')}\n\n"
        f"<b>Статус:</b> {hcode(status)}\n"
        f"<b>Сумма:</b> {hbold(f'{total} {currency}')}\n\n"
        f"👤 {hbold('Покупатель:')}\n{customer_block}\n\n"
        f"🛒 {hbold('Состав заказа:')}\n{items_str}\n\n"
    )

    if customer_note:
        text += f"📝 {hbold('Заметка клиента:')}\n{customer_note}"

    return text


def format_customer_order_details(order: Dict) -> str:
    """
    Форматирует красивую и подробную карточку заказа для клиента.
    """

    status_map = {
        'on-hold': '⏳ В ожидании подтверждения',
        'processing': '🔄 В обработке',
        'completed': '✅ Выполнен',
        'cancelled': '❌ Отменен',
        'refunded': '💰 Возвращен',
        'failed': '❗️ Не удался',
    }
    
    order_number = order.get('number', order.get('id'))
    status_slug = order.get('status', 'unknown')
    status_text = status_map.get(status_slug, status_slug.capitalize())
    total = order.get('total', 'N/A')
    currency = order.get('currency', '')
    
    # Формируем список товаров
    items_list = []
    for item in order.get('line_items', []):
        name = html.escape(item.get('name', 'Неизвестный товар'))
        quantity = item.get('quantity', 0)
        item_total = item.get('total', '0')
        items_list.append(f" • {name} ({quantity} шт.) - {hbold(f'{item_total} {currency}')}")
    items_str = "\n".join(items_list) if items_list else "Состав заказа пуст."

    # Формируем заметку, если она есть
    note = order.get('customer_note')
    note_str = f"\n🗒️ <b>Ваша заметка:</b>\n<i>{html.escape(note)}</i>" if note else ""

    text = (
        f"🧾 {hbold(f'Детали заказа №{order_number}')}\n\n"
        f"<b>Статус:</b> {status_text}\n"
        f"<b>Сумма к оплате:</b> {hbold(f'{total} {currency}')}\n\n"
        f"<b>Состав заказа:</b>\n{items_str}"
        f"{note_str}"
    )
    return text