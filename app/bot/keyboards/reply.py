# backend/app/bot/keyboards/reply.py
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import ReplyKeyboardBuilder

def get_manager_main_menu() -> ReplyKeyboardMarkup:
    """Создает главное меню для менеджера."""
    builder = ReplyKeyboardBuilder()
    builder.row(
        KeyboardButton(text="📦 Заказы"),
        # KeyboardButton(text="📊 Статистика")
    )
    builder.row(
        # KeyboardButton(text="👥 Клиенты"),
        KeyboardButton(text="📤 Рассылка")
    )
    return builder.as_markup(resize_keyboard=True)

def get_order_status_menu() -> ReplyKeyboardMarkup:
    """Создает меню для выбора статуса заказа."""
    builder = ReplyKeyboardBuilder()
    builder.row(
        KeyboardButton(text="⏳ В ожидании (on-hold)"),
        KeyboardButton(text="🔄 В работе (processing)")
    )
    builder.row(
        KeyboardButton(text="✅ Выполненные (completed)"),
        KeyboardButton(text="❌ Отмененные (cancelled)")
    )
    builder.row(KeyboardButton(text="Все активные (on-hold, processing)"))
    builder.row(KeyboardButton(text="◀️ Назад в главное меню"))
    return builder.as_markup(resize_keyboard=True)

def get_back_to_main_menu() -> ReplyKeyboardMarkup:
    """Кнопка для возврата в главное меню."""
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="◀️ Назад в главное меню"))
    return builder.as_markup(resize_keyboard=True)


def get_request_contact_keyboard() -> ReplyKeyboardMarkup:
    """Создает клавиатуру с кнопкой запроса контакта."""
    builder = ReplyKeyboardBuilder()
    builder.button(
        text="📞 Поделиться контактом",
        request_contact=True
    )
    # Добавим кнопку отмены
    builder.row(KeyboardButton(text="Отмена"))
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)