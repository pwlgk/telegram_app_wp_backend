# backend/app/bot/handlers/user.py
import logging
from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message
from aiogram.utils.markdown import hbold, hcode
from aiogram.fsm.context import FSMContext
from aiogram.types import ReplyKeyboardRemove, Contact
from app.bot.states import UserStates
from app.bot.keyboards.reply import get_request_contact_keyboard
from app.services.telegram import TelegramService # Импортируем сервис
from aiogram.types import CallbackQuery

from app.services.woocommerce import WooCommerceService
from app.services.telegram import TelegramService
from app.bot.keyboards.inline import get_main_menu_keyboard
from aiogram.types import InputMediaPhoto # <<< Добавляем импорт
from app.bot.utils import format_customer_info, format_customer_order_details 
from aiogram.exceptions import TelegramBadRequest # <<< Добавляем импорт для обработки ошибок

logger = logging.getLogger(__name__)
user_router = Router(name="user_handlers")

async def send_welcome_message(message: Message):
    """
    Вспомогательная функция для отправки и закрепления приветственного сообщения.
    """
    user_name = message.from_user.full_name
    
    welcome_text = (
        f"👋 Здравствуйте, {hbold(user_name)}!\n\n"
        f"Добро пожаловать в наш магазин. Чтобы посмотреть каталог "
        f"и оформить заказ, нажмите кнопку ниже."
    )
    reply_markup = get_main_menu_keyboard()

    # Отправляем приветственное сообщение
    sent_message = await message.answer(
        text=welcome_text,
        reply_markup=reply_markup
    )
    
    # Пытаемся закрепить это сообщение
    try:
        # disable_notification=True - чтобы не присылать пользователю лишнее уведомление о закреплении
        await sent_message.pin(disable_notification=True)
        logger.info(f"Welcome message pinned for user {message.from_user.id}")
    except TelegramBadRequest as e:
        # Ловим ошибку, если у бота нет прав на закрепление сообщений
        # (например, в группе, где он не администратор)
        logger.warning(f"Failed to pin message for user {message.from_user.id}. Error: {e.message}")
    except Exception as e:
        # Ловим другие возможные ошибки
        logger.error(f"An unexpected error occurred while pinning message: {e}", exc_info=True)



@user_router.message(CommandStart())
async def handle_start(message: Message, wc_service: WooCommerceService): # <<< Добавили wc_service
    """
    Обработчик команды /start.
    Регистрирует пользователя в WooCommerce и отправляет приветствие.
    """
    user = message.from_user
    logger.info(f"User {user.id} ({user.full_name}) started the bot. Registering...")

    # Преобразуем объект User в словарь, который ожидает наш сервис
    user_info = {
        "id": user.id,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "username": user.username
    }
    
    # Вызываем метод регистрации/поиска. Он тихо создаст пользователя, если его нет.
    try:
        customer_id = await wc_service.find_or_create_customer_by_telegram_data(user_info)
        if customer_id:
            logger.info(f"User {user.id} successfully registered/found with customer_id: {customer_id}")
        else:
            logger.error(f"Failed to register user {user.id} in WooCommerce.")
            # Даже если регистрация не удалась, мы все равно должны ответить пользователю
    except Exception as e:
        logger.exception(f"An error occurred during user registration for user_id {user.id}: {e}")
        # И в этом случае тоже отвечаем
    
    await send_welcome_message(message)

@user_router.message(Command("shop"))
async def handle_shop_command(message: Message):
    """
    Обработчик команды /shop.
    Просто отправляет (и закрепляет) сообщение с кнопкой Mini App.
    """
    logger.info(f"User {message.from_user.id} used /shop command.")
    user = message.from_user
    logger.info(f"User {user.id} ({user.full_name}) started the bot. Registering...")

    # Преобразуем объект User в словарь, который ожидает наш сервис
    user_info = {
        "id": user.id,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "username": user.username
    }
# Формируем приветственное сообщение
    welcome_text = (
        f"👋 С возвращением, {hbold(user.full_name)}!\n\n"
        f"Вы можете просмотреть каталог и оформить заказ прямо здесь."
    )
    reply_markup = get_main_menu_keyboard()

    await message.answer(
        text=welcome_text,
        reply_markup=reply_markup
    )
@user_router.message(Command("myorders"))
async def handle_my_orders(message: Message, wc_service: WooCommerceService, tg_service: TelegramService):
    """Обрабатывает команду /myorders, отправляя пользователю список его заказов."""
    user_id = message.from_user.id
    logger.info(f"User {user_id} requested their orders with /myorders.")
    logger.info(f"Handler 'handle_my_orders' triggered by user {message.from_user.id}")

    customer_email = f"tg_{user_id}@telegram.user"
    customer = await wc_service.get_customer_by_email(customer_email)

    if not customer or not customer.get('id'):
        await message.answer("Не удалось найти ваш профиль. Возможно, вы еще не делали заказов.")
        return

    orders, _ = await wc_service.get_orders(customer_id=customer['id'], per_page=5, order='desc')
    response_text = tg_service._format_customer_orders(orders) # Используем метод из сервиса
    await message.answer(response_text)

@user_router.message(F.text.startswith("/order_"))
async def handle_order_details(message: Message, wc_service: WooCommerceService):
    """
    Обрабатывает команду /order_<id>, отправляя красивую карточку заказа с фото.
    """
    try:
        order_id = int(message.text.split("_")[1])
    except (IndexError, ValueError):
        await message.reply("Неверный формат команды. Используйте /myorders, чтобы получить список заказов.")
        return
    
    user_id = message.from_user.id
    logger.info(f"User {user_id} requested details for order_id {order_id}.")

    # 1. Находим пользователя и проверяем права на заказ
    customer_email = f"tg_{user_id}@telegram.user"
    customer = await wc_service.get_customer_by_email(customer_email)
    if not customer or not customer.get('id'):
        await message.answer("Не удалось найти ваш профиль.")
        return

    order = await wc_service.get_order(order_id)
    if not order or order.get('customer_id') != customer.get('id'):
        await message.answer(f"Заказ с номером {order_id} не найден или не принадлежит вам.")
        return
        
    # 2. Получаем изображения для всех товаров в заказе одним запросом
    product_ids = [item['product_id'] for item in order.get('line_items', [])]
    image_urls = []
    if product_ids:
        products, _ = await wc_service.get_products(include=product_ids, per_page=len(product_ids))
        if products:
            # Создаем словарь {product_id: image_url} для удобства
            product_images_map = {
                p['id']: p['images'][0]['src']
                for p in products if p.get('images')
            }
            # Собираем URL изображений в том же порядке, что и товары в заказе
            for item in order.get('line_items', []):
                url = product_images_map.get(item['product_id'])
                if url:
                    image_urls.append(url)
    
    # 3. Форматируем текстовое описание заказа
    details_text = format_customer_order_details(order)
    
    # 4. Отправляем сообщение в зависимости от количества товаров
    try:
        if len(image_urls) == 1:
            # Если товар один, отправляем фото с подписью
            await message.answer_photo(
                photo=image_urls[0],
                caption=details_text
            )
        elif len(image_urls) > 1:
            # Если товаров много, отправляем медиагруппу...
            media_group = [InputMediaPhoto(media=url) for url in image_urls[:10]] # Лимит 10 в медиагруппе
            await message.answer_media_group(media=media_group)
            # ...а затем текстовые детали отдельным сообщением
            await message.answer(text=details_text)
        else:
            # Если изображений нет, просто отправляем текст
            await message.answer(text=details_text)
    except Exception as e:
        logger.error(f"Failed to send order details with photo/media for order {order_id}: {e}")
        # Запасной вариант: если отправка с медиа не удалась, просто шлем текст
        await message.answer(text=details_text)

@user_router.callback_query(F.data.startswith("send_contact:"))
async def handle_send_contact_callback(query: CallbackQuery, state: FSMContext):
    """
    Реагирует на инлайн-кнопку "Отправить контакт",
    запрашивает контакт с помощью Reply-кнопки.
    """
    try:
        order_id = int(query.data.split(":")[1])
    except (IndexError, ValueError):
        await query.answer("Ошибка: неверный ID заказа.", show_alert=True)
        return
        
    # Сохраняем ID заказа в FSM, чтобы знать, к чему относится контакт
    await state.set_state(UserStates.awaiting_contact)
    await state.update_data(order_id=order_id)
    
    await query.message.answer(
        "Нажмите на кнопку ниже, чтобы поделиться вашим контактом.",
        reply_markup=get_request_contact_keyboard()
    )
    # Убираем инлайн-кнопку из предыдущего сообщения
    await query.message.edit_reply_markup(reply_markup=None)
    await query.answer()

@user_router.message(F.text == "Отмена", UserStates.awaiting_contact)
async def handle_contact_cancel(message: Message, state: FSMContext):
    """Отмена отправки контакта."""
    await state.clear()
    await message.answer("Действие отменено.", reply_markup=ReplyKeyboardRemove())

@user_router.callback_query(F.data.startswith("req_contact_mgr:"))
async def handle_request_contact_from_manager(query: CallbackQuery, state: FSMContext):
    """
    Реагирует на кнопку "Поделиться контактом" в сообщении от менеджера.
    """
    # <<< ИЗМЕНЕНИЕ: Извлекаем order_id из callback_data
    try:
        order_id = int(query.data.split(":")[1])
    except (IndexError, ValueError):
        await query.answer("Ошибка: неверный ID заказа в кнопке.", show_alert=True)
        return

    # Сохраняем ID заказа в FSM, чтобы он был доступен на следующем шаге
    await state.set_state(UserStates.awaiting_contact)
    await state.update_data(order_id=order_id)

    await query.message.answer(
        "Нажмите на кнопку ниже, чтобы поделиться вашим контактом.",
        reply_markup=get_request_contact_keyboard()
    )
    await query.message.edit_reply_markup(reply_markup=None) # Убираем инлайн-кнопку
    await query.answer()



@user_router.message(F.contact, UserStates.awaiting_contact)
async def handle_contact_received(message: Message, state: FSMContext, tg_service: TelegramService):
    """
    Ловит отправленный контакт, пересылает менеджерам и сбрасывает состояние.
    """
    contact: Contact = message.contact
    data = await state.get_data()
    order_id = data.get("order_id")
    await state.clear()
    
    # Скрываем reply-клавиатуру
    await message.answer("Спасибо! Ваш контакт получен.", reply_markup=ReplyKeyboardRemove())
    
    # Формируем сообщение для менеджера
    user_info_block = format_customer_info(message.from_user.model_dump())
    
    text_to_manager = (
        f"📞 Новый контакт от клиента по заказу №{hbold(str(order_id))}:\n\n"
        f"{user_info_block}\n"
        f"<b>Номер телефона:</b> {hcode(contact.phone_number)}"
    )
    
    # Отправляем всем менеджерам
    # tg_service.manager_ids уже есть в сервисе
    for manager_id in tg_service.manager_ids:
        await tg_service._send_message_safe(manager_id, text_to_manager)
    
    logger.info(f"User {message.from_user.id} sent contact for order {order_id}")


