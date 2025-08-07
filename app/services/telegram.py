# backend/app/services/telegram.py

import logging
from datetime import datetime
from typing import Dict
from aiogram import Bot
from aiogram.utils.markdown import hbold, hitalic, hlink, hcode
from aiogram.exceptions import TelegramAPIError
from app.bot.utils import format_customer_info # <<< Импортируем новую функцию

from app.core.config import settings
# Импортируем нашу функцию для создания клавиатуры
from app.bot.keyboards.inline import get_admin_order_keyboard, get_post_order_keyboard

logger = logging.getLogger(__name__)

class TelegramNotificationError(Exception):
    """Custom exception for notification errors."""
    pass

class TelegramService:
    """
    Сервис для отправки уведомлений и взаимодействия с Telegram Bot API.
    """
    def __init__(self, bot: Bot):
        if not isinstance(bot, Bot):
             raise ValueError("TelegramService requires an initialized aiogram.Bot instance.")
        self.bot = bot
        self.manager_ids = settings.TELEGRAM_MANAGER_IDS

        if not self.manager_ids:
             logger.warning("Telegram Manager IDs are not configured. Notifications will not be sent.")

    async def _send_message_safe(self, user_id: int, text: str, reply_markup=None, **kwargs):
        """Безопасная отправка сообщения с обработкой ошибок и клавиатурой."""
        try:
            await self.bot.send_message(user_id, text, reply_markup=reply_markup, **kwargs)
            logger.debug(f"Message sent successfully to user {user_id}")
            return True
        except TelegramAPIError as e:
            logger.error(f"Failed to send message to user {user_id}: {e}")
            # Здесь можно добавить логику обработки конкретных ошибок (например, бот заблокирован)
            return False
        except Exception as e:
            logger.exception(f"Unexpected error sending message to user {user_id}: {e}")
            return False

    def _format_order_notification(self, order_details: Dict, user_info: Dict) -> str:
        """Форматирует текст уведомления о новом заказе для менеджера."""
        order_id = order_details.get('id', 'N/A')
        order_number = order_details.get('number', order_id)
        order_total = order_details.get('total', 'N/A')
        currency = order_details.get('currency', '')
        date_created_str = order_details.get('date_created', '')
        
        try:
            if date_created_str and 'T' in date_created_str:
                 dt_obj = datetime.fromisoformat(date_created_str.replace('Z', '+00:00'))
                 formatted_date = dt_obj.strftime('%d.%m.%Y %H:%M:%S %Z')
            else:
                 formatted_date = date_created_str
        except Exception:
            formatted_date = date_created_str

        tg_user_id = user_info.get('id')
        tg_username = user_info.get('username')
        tg_first_name = user_info.get('first_name', '')
        tg_last_name = user_info.get('last_name', '')
        user_link = f"tg://user?id={tg_user_id}"
        user_mention = hlink(f"{tg_first_name} {tg_last_name}".strip() or f"User {tg_user_id}", user_link)
        if tg_username:
            user_mention += f" (@{tg_username})"

        items_str_list = []
        for item in order_details.get('line_items', []):
            item_name = item.get('name', 'Unknown Item')
            quantity = item.get('quantity', '?')
            total_item_price = item.get('total', '?')
            items_str_list.append(f"- {hcode(item_name)} ({quantity} шт.) - {total_item_price} {currency}")
        items_str = "\n".join(items_str_list) if items_str_list else hitalic("Нет данных о товарах")

        customer_note = order_details.get('customer_note')
        note_str = f"\n\n{hbold('Заметка покупателя:')}\n{hitalic(customer_note)}" if customer_note else ""
        
        billing_info = order_details.get('billing', {})
        phone = billing_info.get('phone')
        city = billing_info.get('city')
        contact_info_str = ""
        if phone:
            contact_info_str += f"\n📞 {hbold('Телефон:')} {hcode(phone)}"
        if city:
            contact_info_str += f"\n📍 {hbold('Город:')} {city}"

        admin_url = f"{settings.WOOCOMMERCE_URL.rstrip('/')}/wp-admin/post.php?post={order_id}&action=edit"
        admin_link_str = f"\n\n{hlink('Открыть заказ в WP Admin', admin_url)}"
        customer_block = format_customer_info(user_info, order_details.get('billing', {}))

        message = (
            f"🎉 {hbold('Новый заказ!')} № {hcode(order_number)}\n\n"
            f"🗓️ {hbold('Дата:')} {formatted_date}\n"
            f"👤 {hbold('Покупатель:')} {customer_block}"
            f"{contact_info_str}\n"
            f"\n🛒 {hbold('Состав заказа:')}\n{items_str}\n"
            f"\n💰 {hbold('Итого:')} {hcode(f'{order_total} {currency}')}"
            f"{note_str}"
            f"{admin_link_str}"
        )
        return message

    async def notify_new_order(self, order_details: Dict, user_info: Dict):
        """Отправляет уведомление о новом заказе всем менеджерам с кнопками."""
        if not self.manager_ids:
            return

        order_id = order_details.get('id')
        customer_tg_id = user_info.get('id')
        if not order_id or not customer_tg_id:
            logger.error(f"Cannot create notification: missing order_id or customer_tg_id.")
            return

        message_text = self._format_order_notification(order_details, user_info)
        reply_markup = get_admin_order_keyboard(order_id, customer_tg_id)

        logger.info(f"Sending notification for order {order_id} to {len(self.manager_ids)} managers...")
        for manager_id in self.manager_ids:
            await self._send_message_safe(manager_id, message_text, reply_markup=reply_markup, disable_web_page_preview=True)

    def _format_status_update_for_customer(self, order_number: str, new_status_slug: str) -> str:
        """Форматирует сообщение об обновлении статуса для клиента."""
        status_map = {
            'on-hold': 'В ожидании подтверждения',
            'processing': 'В обработке',
            'completed': 'Выполнен',
            'cancelled': 'Отменен',
            'refunded': 'Возвращен',
            'failed': 'Не удался',
        }
        status_text = status_map.get(new_status_slug, new_status_slug.capitalize())

        message = (
            f"ℹ️ Статус вашего заказа №{hcode(order_number)} обновлен.\n\n"
            f"Новый статус: {hbold(status_text)}"
        )
        return message

    async def notify_customer_status_update(self, customer_tg_id: int, order_id: int, order_number: str, new_status: str):
        """Отправляет уведомление клиенту об изменении статуса заказа."""
        if not customer_tg_id:
            logger.error(f"Cannot notify customer for order {order_id}: customer_tg_id is missing.")
            return

        message_text = self._format_status_update_for_customer(order_number, new_status)
        logger.info(f"Sending status update notification for order {order_id} to customer {customer_tg_id}...")

        await self._send_message_safe(customer_tg_id, message_text)

    def _format_customer_orders(self, orders: list[dict]) -> str:
        """Форматирует список заказов для отправки клиенту."""
        if not orders:
            return "У вас пока нет заказов."

        status_map = {
            'on-hold': '⏳ В ожидании',
            'processing': '🔄 В обработке',
            'completed': '✅ Выполнен',
            'cancelled': '❌ Отменен',
            'refunded': '💰 Возвращен',
            'failed': '❗️ Не удался',
        }

        header = hbold("Ваши последние заказы:\n\n")
        order_lines = []

        # Показываем не более 5 последних заказов, чтобы не спамить
        for order in orders[:5]:
            order_number = order.get('number', order.get('id'))
            date_str = order.get('date_created', '').split('T')[0] # Берем только дату
            status_slug = order.get('status', 'unknown')
            status_text = status_map.get(status_slug, status_slug.capitalize())
            total = order.get('total', 'N/A')
            currency = order.get('currency', '')

            # /order_12345 - делаем команду для просмотра деталей
            order_line = (
                f"{status_text} (№ {hcode(order_number)} от {date_str})\n"
                f"Сумма: {hbold(f'{total} {currency}')}\n"
                f"Подробнее: /order_{order.get('id')}\n"
            )
            order_lines.append(order_line)
        
        return header + "\n".join(order_lines)
    
    async def notify_customer_order_created(self, customer_tg_id: int, order_id: int, order_number: str):
        """Уведомляет клиента о создании заказа и предлагает отправить контакт."""
        text = (
            f"✅ Ваш заказ №{hbold(order_number)} успешно создан!\n\n"
            f"В ближайшее время мы с вами свяжемся для подтверждения деталей.\n\n"
            f"Чтобы ускорить процесс, вы можете отправить нам свой контактный номер телефона."
        )
        keyboard = get_post_order_keyboard(order_id)
        await self._send_message_safe(customer_tg_id, text, reply_markup=keyboard)
