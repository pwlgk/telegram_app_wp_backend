# backend/app/bot/handlers/callbacks.py
import logging
from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery
from aiogram.exceptions import TelegramBadRequest

from app.services.woocommerce import WooCommerceService
from app.services.telegram import TelegramService
from app.bot.keyboards.inline import STATUS_MAP

logger = logging.getLogger(__name__)

# Создаем роутер для колбэков
callback_router = Router()

@callback_router.callback_query(F.data.startswith("status:"))
async def handle_status_update_callback(
    callback_query: CallbackQuery,
    bot: Bot, # Получаем бота из middleware (будет настроено в main.py)
    # Эти сервисы нужно будет передать в хендлер. 
    # Сделаем это через middleware или передачу в dp.
    wc_service: WooCommerceService, 
    tg_service: TelegramService,
):
    
    logger.info(f"Handler 'handle_status_update_callback' triggered by user {callback_query.from_user.id} with data: {callback_query.data}")

    """
    Обрабатывает нажатия на кнопки изменения статуса заказа.
    """
    await callback_query.answer(text="Обрабатываю запрос...") # Ответ, чтобы убрать "часики" с кнопки

    try:
        # 1. Парсим callback_data
        # "status:proc:123" -> ["status", "proc", "123"]
        _, status_key, order_id_str = callback_query.data.split(":")
        order_id = int(order_id_str)
        
        status_info = STATUS_MAP.get(status_key)
        if not status_info:
            logger.warning(f"Received unknown status key: {status_key}")
            await callback_query.message.reply("Ошибка: неизвестный статус.")
            return

        new_status_slug = status_info["slug"]
        new_status_text = status_info["text"]
        logger.info(f"Manager {callback_query.from_user.id} requested status change for order {order_id} to '{new_status_slug}'")

        # 2. Обновляем статус в WooCommerce
        updated_order = await wc_service.update_order_status(order_id, new_status_slug)
        if not updated_order:
            await callback_query.message.edit_text(
                f"{callback_query.message.html_text}\n\n"
                f"❌ <b>Ошибка:</b> Не удалось обновить статус заказа №{order_id} в WooCommerce.",
                disable_web_page_preview=True
            )
            return

        # 3. Уведомляем клиента (если у него есть tg_id)
        customer_tg_id = None
        for meta in updated_order.get('meta_data', []):
            if meta.get('key') == '_telegram_user_id':
                customer_tg_id = int(meta.get('value'))
                break
        
        if customer_tg_id:
            await tg_service.notify_customer_status_update(
                customer_tg_id=customer_tg_id,
                order_id=order_id,
                order_number=updated_order.get('number', str(order_id)),
                new_status=new_status_slug
            )
        
        # 4. Редактируем исходное сообщение в чате менеджера
        await callback_query.message.edit_text(
            f"{callback_query.message.html_text}\n\n"
            f"✅ <b>Статус обновлен на «{new_status_text}»</b> (менеджером {callback_query.from_user.full_name})",
            disable_web_page_preview=True
        )
        logger.info(f"Order {order_id} status successfully updated and notification sent.")

    except (ValueError, IndexError) as e:
        logger.error(f"Error parsing callback_data '{callback_query.data}': {e}")
        await callback_query.message.reply("Ошибка: неверный формат данных.")
    except TelegramBadRequest as e:
        # Ошибка, если сообщение слишком старое для редактирования
        logger.warning(f"Could not edit message for order status update: {e}")
        await callback_query.message.answer(f"Статус заказа обновлен, но не удалось изменить это сообщение (возможно, оно слишком старое).")
    except Exception as e:
        logger.exception(f"Unexpected error in status update callback: {e}")
        await callback_query.message.reply("Произошла непредвиденная ошибка при обработке запроса.")