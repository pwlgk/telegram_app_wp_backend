# backend/app/bot/handlers/user.py
import logging
from aiogram import Router, types, F
from aiogram.filters import CommandStart
from aiogram.utils.markdown import hbold

from app.bot.keyboards.inline import get_main_menu_keyboard # Импортируем нашу клавиатуру

# Создаем роутер для пользовательских команд/сообщений
user_router = Router(name="user_handlers")
logger = logging.getLogger(__name__)

@user_router.message(CommandStart())
async def handle_start(message: types.Message):
    """
    Обработчик команды /start.
    Отправляет приветственное сообщение и кнопку для открытия Mini App.
    """
    user_name = message.from_user.full_name
    user_id = message.from_user.id
    logger.info(f"User {user_id} ({user_name}) started the bot.")

    # Формируем приветственное сообщение
    welcome_text = (
        f"👋 Здравствуйте, {hbold(user_name)}!\n\n"
        f"Добро пожаловать в наш магазин. Вы можете просмотреть каталог "
        f"и оформить заказ прямо здесь."
    )

    # Получаем клавиатуру с кнопкой WebApp
    reply_markup = get_main_menu_keyboard()

    # Отправляем сообщение с клавиатурой
    await message.answer(
        text=welcome_text,
        reply_markup=reply_markup
    )

# Можно добавить обработчик для callback'ов, если будут другие инлайн-кнопки
@user_router.callback_query(F.data == "shop_unavailable")
async def handle_shop_unavailable(callback_query: types.CallbackQuery):
    """Обработчик нажатия на кнопку-плейсхолдер, если магазин недоступен."""
    await callback_query.answer(
        "Извините, магазин сейчас недоступен. Пожалуйста, попробуйте позже.",
        show_alert=True # Показать уведомление как alert
    )
    logger.warning(f"User {callback_query.from_user.id} clicked 'shop_unavailable' button.")

# Можно добавить обработчик для любых других сообщений от пользователя,
# если не планируется другая логика бота, кроме запуска Mini App.
# @user_router.message()
# async def handle_other_messages(message: types.Message):
#     """Обрабатывает любые другие текстовые сообщения."""
#     logger.debug(f"Received message from {message.from_user.id}: {message.text[:50]}")
#     # Можно просто напоминать про кнопку
#     await message.reply(
#         "Используйте кнопку ниже, чтобы открыть магазин.",
#         reply_markup=get_main_menu_keyboard()
#     )