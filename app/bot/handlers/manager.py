# backend/app/bot/handlers/manager.py
import asyncio
import html
import logging
from typing import Dict
from aiogram import Router, F, Bot
from aiogram.filters import Command, StateFilter, or_f # <<< Добавляем or_f
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, ReplyKeyboardRemove
from aiogram.exceptions import TelegramAPIError
from datetime import datetime, timedelta # <<< Добавляем импорт
from app.bot.keyboards.inline import get_request_contact_from_manager_keyboard, get_stats_menu_keyboard # <<< Добавляем

from app.core.config import settings
from app.services.woocommerce import WooCommerceService
from app.services.telegram import TelegramService
from app.bot.keyboards.reply import get_manager_main_menu, get_order_status_menu, get_back_to_main_menu
from app.bot.keyboards.inline import get_customers_menu_keyboard, get_customers_pagination_keyboard # <<< Добавляем
from app.bot.states import ManagerStates
from app.bot.utils import format_customer_info
from app.bot.callback_data import ManagerCallback # <<< Импортируем фабрику
from app.bot.utils import format_customer_info, format_order_details # <<< Добавляем новый форматтер
from app.bot.keyboards.inline import get_manager_orders_keyboard, get_manager_order_details_keyboard # <<< Добавляем новую клавиатуру
from aiogram.utils.markdown import  hlink, hcode

logger = logging.getLogger(__name__)
manager_router = Router(name="manager_handlers")
manager_router.message.filter(F.from_user.id.in_(settings.TELEGRAM_MANAGER_IDS))
manager_router.callback_query.filter(F.from_user.id.in_(settings.TELEGRAM_MANAGER_IDS))


# === ГЛАВНОЕ МЕНЮ ===
@manager_router.message(Command("panel"))
@manager_router.message(F.text == "◀️ Назад в главное меню")
async def show_manager_panel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Добро пожаловать в панель менеджера!", reply_markup=get_manager_main_menu())


# === РАБОТА С ЗАКАЗАМИ (Reply Keyboard) ===
@manager_router.message(F.text == "📦 Заказы")
async def show_order_statuses(message: Message):
    await message.answer("Выберите статус заказов для просмотра:", reply_markup=get_order_status_menu())

# --- Новая функция для отображения списка заказов ---
async def send_orders_list(target: Message | CallbackQuery, wc_service: WooCommerceService, status_slug: str, page: int = 1):
    is_callback = isinstance(target, CallbackQuery)
    message = target.message if is_callback else target

    try:
        orders, headers = await wc_service.get_orders(status=status_slug.split(','), page=page, per_page=5, order='desc')
        total_pages = int(headers.get('x-wp-totalpages', 1)) if headers else 1

        if not orders:
            await message.answer("Заказы с таким статусом не найдены.")
            return

        keyboard = get_manager_orders_keyboard(orders, page, total_pages, status_slug)
        text = f"<b>Заказы со статусом '{status_slug}'</b> (Стр. {page}/{total_pages})"
        
        if is_callback:
            await message.edit_text(text, reply_markup=keyboard)
        else:
            await message.answer(text, reply_markup=keyboard)

    except Exception as e:
        logger.error(f"Failed to fetch orders for manager: {e}")
        await message.answer("Не удалось получить список заказов.")
    
    if is_callback:
        await target.answer()

# --- Хендлер для Reply кнопок статусов ---
@manager_router.message(F.text.contains(" (")) # Ловим кнопки статусов
async def list_orders_by_status(message: Message, wc_service: WooCommerceService):
    status_text = message.text
    status_slug_map = {
        "В ожидании": "on-hold", "В работе": "processing",
        "Выполненные": "completed", "Отмененные": "cancelled",
        "Все активные": "on-hold,processing"
    }
    
    status_slug = next((slug for key, slug in status_slug_map.items() if key in status_text), None)

    if not status_slug:
        await message.reply("Неизвестный статус.", reply_markup=get_manager_main_menu())
        return

    await send_orders_list(message, wc_service, status_slug, page=1)

# === ОБРАБОТЧИКИ КОЛБЭКОВ ЗАКАЗОВ ===

# --- Пагинация ---
@manager_router.callback_query(ManagerCallback.filter(F.target == "orders" and F.action == "page"))
async def handle_orders_pagination(query: CallbackQuery, callback_data: ManagerCallback, wc_service: WooCommerceService):
    await send_orders_list(query, wc_service, status_slug=callback_data.value, page=callback_data.page)

# --- Детали заказа (пока заглушка) ---
@manager_router.callback_query(ManagerCallback.filter(F.target == "orders" and F.action == "details"))
async def handle_order_details(query: CallbackQuery, callback_data: ManagerCallback, wc_service: WooCommerceService, bot: Bot): # <<< Добавили bot
    order_id = callback_data.order_id
    
    order = await wc_service.get_order(order_id)
    if not order:
        await query.answer("Не удалось найти заказ.", show_alert=True)
        return

    # <<< ВЫЗЫВАЕМ АСИНХРОННО И ПЕРЕДАЕМ bot
    text = await format_order_details(order, bot) 
    
    keyboard = get_manager_order_details_keyboard(
        order=order,
        current_page=callback_data.page,
        status_slug=callback_data.value
    )
    
    await query.message.edit_text(text, reply_markup=keyboard, disable_web_page_preview=True)
    await query.answer()

# --- Смена статуса заказа ---
@manager_router.callback_query(ManagerCallback.filter(F.target == "orders" and F.action == "set_status"))
async def handle_set_order_status(
    query: CallbackQuery, 
    callback_data: ManagerCallback, 
    wc_service: WooCommerceService, 
    tg_service: TelegramService,
    bot: Bot # <<< Добавили bot
):
    order_id = callback_data.order_id
    new_status = callback_data.value
    
    await query.answer(f"Меняю статус на '{new_status}'...")

    updated_order = await wc_service.update_order_status(order_id, new_status)
    if not updated_order:
        await query.answer("Ошибка! Не удалось обновить статус в WooCommerce.", show_alert=True)
        return

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
            new_status=new_status
        )

    # Обновляем сообщение у менеджера, показывая новые детали и новые кнопки
    # <<< ВЫЗЫВАЕМ АСИНХРОННО И ПЕРЕДАЕМ bot
    text = await format_order_details(updated_order, bot)
    
    keyboard = get_manager_order_details_keyboard(
        order=updated_order,
        current_page=callback_data.page,
        status_slug=callback_data.value # Передаем старый фильтр, чтобы кнопка "Назад" работала
    )
    
    await query.message.edit_text(text, reply_markup=keyboard, disable_web_page_preview=True)
    await query.answer("Статус успешно обновлен!")

@manager_router.callback_query(ManagerCallback.filter(F.target == "customer" and F.action == "contact"))
async def handle_contact_customer_start(query: CallbackQuery, callback_data: ManagerCallback, state: FSMContext):
    customer_tg_id = callback_data.value
    order_id = callback_data.order_id

    # Сохраняем ID клиента и заказа в FSM для следующего шага
    await state.set_state(ManagerStates.message_to_customer)
    await state.update_data(contact_customer_id=customer_tg_id, contact_order_id=order_id)
    
    await query.message.answer(
        f"Введите сообщение для клиента по заказу №{order_id}.\n"
        "Можно отправлять текст, фото, документы.\n\n"
        "Для отмены нажмите /cancel.",
        # Убираем reply-клавиатуру, чтобы не мешала
        reply_markup=ReplyKeyboardRemove()
    )
    await query.answer()

# --- Отмена режима связи ---
@manager_router.message(Command("cancel"), StateFilter(ManagerStates.message_to_customer))
async def handle_contact_customer_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Действие отменено.", reply_markup=get_manager_main_menu())


# --- Отправка сообщения клиенту ---
# Ловим любое сообщение (текст, фото и т.д.), когда находимся в нужном состоянии
@manager_router.message(StateFilter(ManagerStates.message_to_customer), or_f(F.text, F.photo, F.document, F.sticker))
async def handle_send_message_to_customer(message: Message, state: FSMContext, bot: Bot):
    # Достаем ID клиента из FSM
    data = await state.get_data()
    customer_tg_id = data.get('contact_customer_id')
    order_id = data.get('contact_order_id')
    
    if not customer_tg_id:
        await message.reply("Ошибка: не удалось определить клиента. Попробуйте снова.")
        await state.clear()
        return

    try:
        # Формируем префикс для сообщения клиенту
        prefix = f"Сообщение по заказу №{order_id}:\n\n"
        
        # message.copy_to() - самый простой способ переслать сообщение
        # со всем содержимым (фото, текст, стили).
        # Но он не позволяет добавить свой текст.
        # Поэтому делаем вручную:
        
        reply_markup = get_request_contact_from_manager_keyboard(order_id)
        
        if message.text:
            await bot.send_message(
                customer_tg_id, 
                prefix + message.text, 
                reply_markup=reply_markup
            )
        elif message.photo:
            await bot.send_photo(
                customer_tg_id, 
                photo=message.photo[-1].file_id, 
                caption=prefix + (message.caption or ""),
                reply_markup=reply_markup
            )
        elif message.document:
            await bot.send_document(
                customer_tg_id,
                document=message.document.file_id,
                caption=prefix + (message.caption or ""),
                reply_markup=reply_markup
            )
        else: # Стикеры и прочее
            # Для стикеров и других типов, которые не поддерживают клавиатуру,
            # отправляем ее отдельным сообщением.
            await message.copy_to(customer_tg_id)
            await bot.send_message(
                customer_tg_id, 
                f"Если потребуется, вы можете отправить свой контакт по заказу №{order_id}, нажав на кнопку ниже.",
                reply_markup=reply_markup
            )

        # Сообщаем менеджеру об успехе
        await message.answer("✅ Сообщение успешно отправлено клиенту.", reply_markup=get_manager_main_menu())
        logger.info(f"Manager {message.from_user.id} sent a message to customer {customer_tg_id} regarding order {order_id}")

    except TelegramAPIError as e:
        # Если пользователь заблокировал бота, ловим ошибку
        logger.error(f"Failed to send message to customer {customer_tg_id}: {e}")
        await message.answer(
            f"❌ Не удалось отправить сообщение. "
            f"Возможно, клиент заблокировал бота или произошла другая ошибка.",
            reply_markup=get_manager_main_menu()
        )
    finally:
        # Очищаем состояние в любом случае
        await state.clear()
# === РАБОТА С КЛИЕНТАМИ ===
# === РАБОТА С КЛИЕНТАМИ ===

# --- Главное меню раздела ---
@manager_router.message(F.text == "👥 Клиенты")
async def customers_main_menu(message: Message):
    text = "Выберите действие для управления клиентами:"
    await message.answer(text, reply_markup=get_customers_menu_keyboard())

# --- Показ общего числа клиентов ---
@manager_router.callback_query(ManagerCallback.filter(F.target == "customers" and F.action == "total"))
async def show_total_customers(query: CallbackQuery, wc_service: WooCommerceService):
    await query.answer("Загружаю данные...")
    _, headers = await wc_service.get_customers(per_page=1)
    total_customers = headers.get('x-wp-total', 'N/A') if headers else 'N/A'
    await query.message.answer(f"👥 Общее количество зарегистрированных клиентов: <b>{total_customers}</b>")

# --- Начало поиска клиента ---
@manager_router.callback_query(ManagerCallback.filter(F.target == "customers" and F.action == "search_start"))
async def customer_search_start(query: CallbackQuery, state: FSMContext):
    await state.set_state(ManagerStates.customer_search_query)
    await query.message.edit_text(
        "Введите ID, имя, email или телефон клиента для поиска:",
        reply_markup=None # Убираем кнопки
    )
    await query.answer()

# --- Обработка поискового запроса ---
@manager_router.message(ManagerStates.customer_search_query)
async def customer_search_process(message: Message, state: FSMContext, wc_service: WooCommerceService, bot: Bot): # <<< Добавили bot
    await state.clear()
    query = message.text
    await message.answer(f"Ищу клиентов по запросу: '{query}'...")
    
    customers, _ = await wc_service.get_customers(search=query, per_page=20)
    
    if not customers:
        await message.answer(f"Клиенты по запросу '{query}' не найдены.", reply_markup=get_manager_main_menu())
        return

    # Отправляем список найденных клиентов одним сообщением
    await send_customers_list_as_message(message, customers, bot) # <<< Передаем bot
    await message.answer("Поиск завершен.", reply_markup=get_manager_main_menu())

# --- Показ списка клиентов (первая страница) ---
@manager_router.callback_query(ManagerCallback.filter(F.target == "customers" and F.action == "list"))
async def customers_list_start(query: CallbackQuery, callback_data: ManagerCallback, wc_service: WooCommerceService, bot: Bot): # <<< Добавили bot
    await show_customers_page(query, wc_service, bot, page=callback_data.page or 1) # <<< Передаем bot
    await query.answer()

# --- Пагинация списка клиентов ---
@manager_router.callback_query(ManagerCallback.filter(F.target == "customers" and F.action == "page"))
async def customers_list_pagination(query: CallbackQuery, callback_data: ManagerCallback, wc_service: WooCommerceService, bot: Bot): # <<< Добавили bot
    await show_customers_page(query, wc_service, bot, page=callback_data.page) # <<< Передаем bot
    await query.answer()

# --- Вспомогательная функция для отображения страницы клиентов ---
async def show_customers_page(target: Message | CallbackQuery, wc_service: WooCommerceService, bot: Bot, page: int): # <<< Добавили bot
    is_callback = isinstance(target, CallbackQuery)
    message = target.message if is_callback else target
    
    customers, headers = await wc_service.get_customers(per_page=20, page=page)
    total_pages = int(headers.get('x-wp-totalpages', 1)) if headers else 1

    if not customers:
        await message.edit_text("Клиенты не найдены.")
        return

    # Отправляем список в виде одного большого сообщения
    await send_customers_list_as_message(message, customers, bot, is_edit=is_callback) # <<< Передаем bot
    
    # Отправляем клавиатуру пагинации отдельным сообщением
    # (или редактируем, если это уже сообщение с пагинацией)
    pagination_keyboard = get_customers_pagination_keyboard(page, total_pages)
    # Ищем, было ли у исходного сообщения меню пагинации
    try:
        if is_callback and target.message.reply_markup and "customers" in target.message.reply_markup.inline_keyboard[0][0].callback_data:
            await target.message.edit_reply_markup(reply_markup=pagination_keyboard)
        else:
            await message.answer("Навигация по списку:", reply_markup=pagination_keyboard)
    except TelegramAPIError as e:
        if "message is not modified" in e.message:
            logger.debug("Pagination keyboard is not modified, skipping edit.")
        else:
            raise e # Пробрасываем другие ошибки


# --- Вспомогательная функция для форматирования и отправки списка клиентов ---
async def send_customers_list_as_message(message: Message, customers: list[dict], bot: Bot, is_edit: bool = False):
    """
    Асинхронно получает актуальные данные из TG для каждого клиента и формирует список.
    """
    
    # --- Получаем актуальные данные из TG параллельно ---
    tg_ids_to_fetch = [
        int(meta['value'])
        for customer in customers
        for meta in customer.get('meta_data', [])
        if meta.get('key') == '_telegram_user_id' and meta.get('value')
    ]
    
    # Запускаем все запросы к get_chat одновременно
    tasks = [bot.get_chat(chat_id=tg_id) for tg_id in tg_ids_to_fetch]
    # return_exceptions=True, чтобы одна ошибка не сломала все
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Создаем словарь {tg_id: chat_object} для быстрого доступа
    actual_tg_data = {
        res.id: res for res in results if not isinstance(res, Exception)
    }

    # --- Формируем строки списка ---
    response_lines = []
    for i, customer in enumerate(customers, 1):
        tg_id_str = next((meta['value'] for meta in customer.get('meta_data', []) if meta['key'] == '_telegram_user_id'), None)
        
        # Данные из WooCommerce
        billing_first_name = html.escape(customer.get('first_name', ''))
        billing_last_name = html.escape(customer.get('last_name', ''))
        phone = customer.get('billing', {}).get('phone', '')

        name_str = f"{billing_first_name} {billing_last_name}".strip() or "Имя не указано"
        username_str = ""
        
        # Если есть TG ID, пытаемся взять актуальные данные
        if tg_id_str:
            tg_id = int(tg_id_str)
            chat_info = actual_tg_data.get(tg_id)
            if chat_info:
                # Берем имя и юзернейм из свежих данных Telegram
                tg_first_name = html.escape(chat_info.first_name or '')
                tg_last_name = html.escape(chat_info.last_name or '')
                name_str = f"{tg_first_name} {tg_last_name}".strip()
                if chat_info.username:
                    username_str = f" (@{chat_info.username})"

            # В любом случае, делаем имя кликабельной ссылкой
            line = f"{i}. {hlink(name_str, f'tg://user?id={tg_id}')}{username_str}"
        else:
            line = f"{i}. {name_str}"
        
        if phone:
            line += f" - {hcode(phone)}"
            
        response_lines.append(line)

    response_text = "\n".join(response_lines)
    
    if is_edit:
        try:
            await message.edit_text(response_text)
        except TelegramAPIError as e:
            if "message is not modified" in e.message:
                logger.debug("Customer list message is not modified, skipping edit.")
            else:
                raise e # Пробрасываем другие ошибки
    else:
        await message.answer(response_text)

# === МАССОВАЯ РАССЫЛКА ===
@manager_router.message(F.text == "📤 Рассылка")
async def mailing_start(message: Message, state: FSMContext):
    await state.set_state(ManagerStates.mailing_confirm)
    await message.answer(
        "<b>ВНИМАНИЕ!</b> Следующее сообщение будет отправлено ВСЕМ пользователям, которые запускали бота.\n"
        "Для отмены введите /cancel.\n\n"
        "Введите текст рассылки:",
        reply_markup=ReplyKeyboardRemove()
    )

@manager_router.message(Command("cancel"), StateFilter(ManagerStates.mailing_confirm))
async def mailing_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Рассылка отменена.", reply_markup=get_manager_main_menu())

@manager_router.message(ManagerStates.mailing_confirm)
async def mailing_process(message: Message, state: FSMContext, wc_service: WooCommerceService, bot: Bot):
    await state.clear()
    await message.answer("Начинаю рассылку... Это может занять время.", reply_markup=get_manager_main_menu())

    # Получаем ВСЕХ клиентов. В проде нужно делать это с пагинацией.
    all_customers, _ = await wc_service.get_customers(per_page=100) # Ограничение для примера
    
    if not all_customers:
        await message.answer("Не найдено ни одного клиента для рассылки.")
        return

    sent_count = 0
    failed_count = 0
    skipped_count = 0

    for customer in all_customers:
        tg_id = None
        
        # Способ 1: Ищем ID в мета-данных (предпочтительный)
        for meta in customer.get('meta_data', []):
            if meta.get('key') == '_telegram_user_id':
                try:
                    tg_id = int(meta.get('value'))
                    break
                except (ValueError, TypeError):
                    continue
        
        # Способ 2 (Fallback): Если мета-поля нет, пытаемся извлечь ID из email
        if not tg_id:
            email = customer.get('email', '')
            if email.startswith('tg_') and email.endswith('@telegram.user'):
                try:
                    # Извлекаем ID из "tg_12345678@telegram.user"
                    tg_id_str = email.split('@')[0].replace('tg_', '')
                    tg_id = int(tg_id_str)
                    logger.debug(f"Extracted tg_id {tg_id} from email for customer {customer.get('id')}")
                except (ValueError, TypeError):
                    pass # Если email в неверном формате, пропускаем

        if tg_id:
            try:
                # message.copy_to() - удобный способ переслать сообщение
                await message.copy_to(chat_id=tg_id)
                sent_count += 1
                await asyncio.sleep(0.1) # Пауза, чтобы не попасть под лимиты Telegram
            except TelegramAPIError as e:
                logger.warning(f"Failed to send broadcast message to user {tg_id}: {e}")
                failed_count += 1
        else:
            # Пользователи, созданные не через бота, будут пропущены
            skipped_count += 1
    
    report_text = (
        f"✅ Рассылка завершена!\n\n"
        f"Успешно отправлено: {sent_count}\n"
        f"Не удалось отправить: {failed_count} (пользователи заблокировали бота)\n"
    )
    if skipped_count > 0:
        report_text += f"Пропущено клиентов (не из TG): {skipped_count}"

    await message.answer(report_text)



# === СТАТИСТИКА ===

@manager_router.message(F.text == "📊 Статистика")
async def stats_main_menu(message: Message):
    """Показывает меню выбора периода для статистики."""
    text = "Выберите период для получения отчета о продажах:"
    await message.answer(text, reply_markup=get_stats_menu_keyboard())

def format_sales_report(report_data: Dict, period_text: str) -> str:
    """Форматирует данные отчета о продажах в читаемое сообщение."""
    if not report_data:
        return f"Нет данных о продажах за период: <b>{period_text}</b>"

    total_sales = report_data.get('total_sales', 0)
    net_sales = report_data.get('net_sales', 0)
    average_sales = report_data.get('average_sales', 0)
    total_orders = report_data.get('total_orders', 0)
    total_items = report_data.get('total_items', 0)

    text = (
        f"📈 <b>Отчет о продажах за {period_text}</b>\n\n"
        f"<b>Всего заказов:</b> {total_orders} шт.\n"
        f"<b>Продано товаров:</b> {total_items} шт.\n"
        f"<b>Чистая выручка:</b> {net_sales} RUB\n"
        f"<b>Общая выручка:</b> {total_sales} RUB\n"
        f"<b>Средний чек:</b> {average_sales} RUB\n"
    )
    return text

@manager_router.callback_query(ManagerCallback.filter(F.target == "stats" and F.action == "get"))
async def get_sales_stats(query: CallbackQuery, callback_data: ManagerCallback, wc_service: WooCommerceService):
    period = callback_data.value
    await query.answer(f"Загружаю отчет...")

    report_list = None
    period_text = ""

    today = datetime.utcnow().date()
    
    if period == "today":
        period_text = "сегодня"
        report_list = await wc_service.get_sales_report(date_min=today, date_max=today)
    elif period == "week":
        period_text = "текущую неделю"
        report_list = await wc_service.get_sales_report(period="week")
    elif period == "month":
        period_text = "текущий месяц"
        report_list = await wc_service.get_sales_report(period="month")

    report = report_list[0] if report_list else None

    if report is None:
        await query.message.edit_text(f"Нет данных о продажах за <b>{period_text}</b>.")
        return

    response_text = format_sales_report(report, period_text)
    await query.message.edit_text(response_text)