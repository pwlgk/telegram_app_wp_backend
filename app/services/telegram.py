# backend/app/services/telegram.py
from datetime import datetime
import logging
from typing import List, Dict, Optional, Any
from aiogram import Bot
from aiogram.utils.markdown import hbold, hitalic, hlink, hcode
from aiogram.exceptions import TelegramAPIError

from app.core.config import settings

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

    async def _send_message_safe(self, user_id: int, text: str, **kwargs):
        """Безопасная отправка сообщения с обработкой ошибок."""
        try:
            await self.bot.send_message(user_id, text, **kwargs)
            logger.debug(f"Message sent successfully to user {user_id}")
            return True
        except TelegramAPIError as e:
            logger.error(f"Failed to send message to user {user_id}: {e}")
            # Здесь можно добавить логику обработки конкретных ошибок
            # (например, бот заблокирован пользователем)
            return False
        except Exception as e:
            logger.exception(f"Unexpected error sending message to user {user_id}: {e}")
            return False

    def _format_order_notification(self, order_details: Dict, user_info: Dict) -> str:
        """Форматирует текст уведомления о новом заказе для менеджера."""
        order_id = order_details.get('id', 'N/A')
        order_number = order_details.get('number', order_id) # WC может использовать 'number'
        order_total = order_details.get('total', 'N/A')
        currency = order_details.get('currency', '')
        date_created_str = order_details.get('date_created', '')
        # Попробуем красиво отформатировать дату (опционально)
        try:
            if date_created_str and 'T' in date_created_str:
                 dt_obj = datetime.fromisoformat(date_created_str.replace('Z', '+00:00'))
                 # Форматируем в более читаемый вид (можно настроить локаль)
                 formatted_date = dt_obj.strftime('%d.%m.%Y %H:%M:%S %Z')
            else:
                 formatted_date = date_created_str
        except Exception:
            formatted_date = date_created_str


        # Информация о покупателе
        tg_user_id = user_info.get('id')
        tg_username = user_info.get('username')
        tg_first_name = user_info.get('first_name', '')
        tg_last_name = user_info.get('last_name', '')
        user_link = f"tg://user?id={tg_user_id}"
        user_mention = hlink(f"{tg_first_name} {tg_last_name}".strip() or f"User {tg_user_id}", user_link)
        if tg_username:
            user_mention += f" (@{tg_username})"

        # Состав заказа (упрощенно)
        items_str_list = []
        for item in order_details.get('line_items', []):
            item_name = item.get('name', 'Unknown Item')
            quantity = item.get('quantity', '?')
            price = item.get('price', '?') # Цена за единицу
            total_item_price = item.get('total', '?') # Общая цена по позиции
            items_str_list.append(f"- {hcode(item_name)} ({quantity} шт.) - {total_item_price} {currency}")
        items_str = "\n".join(items_str_list) if items_str_list else hitalic("Нет данных о товарах")

        # Заметка покупателя
        customer_note = order_details.get('customer_note')
        note_str = f"\n\n{hbold('Заметка покупателя:')}\n{hitalic(customer_note)}" if customer_note else ""

        # Ссылка на заказ в админке WP (если возможно сформировать)
        admin_url = f"{settings.WOOCOMMERCE_URL.rstrip('/')}/wp-admin/post.php?post={order_id}&action=edit"
        admin_link_str = f"\n\n{hlink('Открыть заказ в WP Admin', admin_url)}"

        # Собираем сообщение
        message = (
            f"🎉 {hbold('Новый заказ!')} № {hcode(order_number)}\n\n"
            f"🗓️ {hbold('Дата:')} {formatted_date}\n"
            f"👤 {hbold('Покупатель:')} {user_mention}\n"
            # f"📞 {hbold('Телефон:')} {order_details.get('billing', {}).get('phone', hitalic('Не указан'))}\n" # Если собираем телефон
            # f"📧 {hbold('Email:')} {order_details.get('billing', {}).get('email', hitalic('Не указан'))}\n" # Если собираем email
            f"\n🛒 {hbold('Состав заказа:')}\n{items_str}\n"
            f"\n💰 {hbold('Итого:')} {hcode(f'{order_total} {currency}')}"
            f"{note_str}"
            f"{admin_link_str}" # Добавляем ссылку на админку
        )
        return message


    async def notify_new_order(self, order_details: Dict, user_info: Dict):
        """
        Отправляет уведомление о новом заказе всем менеджерам.

        Args:
            order_details: Словарь с данными созданного заказа из WooCommerce.
            user_info: Словарь с данными пользователя из Telegram initData.
        """
        if not self.manager_ids:
            logger.warning("Cannot send order notification: Manager IDs are not set.")
            return

        if not order_details or not user_info:
             logger.error("Cannot send notification: Missing order_details or user_info.")
             return

        message_text = self._format_order_notification(order_details, user_info)

        logger.info(f"Sending notification for order {order_details.get('id')} to {len(self.manager_ids)} managers...")

        success_count = 0
        for manager_id in self.manager_ids:
            if await self._send_message_safe(manager_id, message_text, disable_web_page_preview=True):
                success_count += 1

        if success_count == len(self.manager_ids):
             logger.info(f"Notification for order {order_details.get('id')} sent successfully to all managers.")
        else:
             logger.warning(f"Notification for order {order_details.get('id')} sent to {success_count}/{len(self.manager_ids)} managers.")
        # Можно выбросить исключение, если ни одно уведомление не было отправлено
        # if success_count == 0:
        #     raise TelegramNotificationError("Failed to send notification to any manager.")
    
    def _format_status_update_for_customer(self, order_number: str, new_status: str) -> str:
        """Форматирует сообщение об обновлении статуса для клиента."""
        status_map = {
            'on-hold': 'В ожидании подтверждения',
            'processing': 'В обработке',
            'completed': 'Выполнен (Отправлен)',
            'cancelled': 'Отменен',
            'refunded': 'Возвращен',
            'failed': 'Не удался',
            # Добавьте другие статусы WooCommerce по необходимости
        }
        status_text = status_map.get(new_status, new_status.capitalize()) # Используем понятный текст или сам статус

        message = (
            f"ℹ️ Статус вашего заказа №{hcode(order_number)} обновлен.\n\n"
            f"Новый статус: {hbold(status_text)}"
        )
        # Можно добавить детали или ссылку на /myorders
        # message += "\n\nВы можете проверить детали командой /myorders"
        return message

    async def notify_customer_status_update(
            self,
            customer_tg_id: int,
            order_id: int, # ID заказа для логов
            order_number: str, # Номер заказа для сообщения
            new_status: str
        ):
        """Отправляет уведомление клиенту об изменении статуса заказа."""
        if not customer_tg_id:
            logger.error(f"Cannot notify customer for order {order_id}: customer_tg_id is missing.")
            return

        message_text = self._format_status_update_for_customer(order_number, new_status)
        logger.info(f"Sending status update notification for order {order_id} to customer {customer_tg_id}...")

        if await self._send_message_safe(customer_tg_id, message_text):
            logger.info(f"Status update notification sent successfully to customer {customer_tg_id}.")
        else:
            # Ошибка уже залогирована в _send_message_safe
            logger.warning(f"Failed to send status update notification to customer {customer_tg_id}.")
            # Можно добавить доп. логику, если нужно (например, уведомить менеджера о несработавшем уведомлении)