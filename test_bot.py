import asyncio
import os
from aiogram import Bot, Dispatcher, types
from aiogram.types import Message
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.client.default import DefaultBotProperties
from dotenv import load_dotenv

# Загружаем .env
load_dotenv()

# Получаем токен
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Создаём бота с parse_mode
bot = Bot(
    token=TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

# Создаём диспетчер
dp = Dispatcher()

# Обработка команды /start
@dp.message(CommandStart())
async def handle_start(message: Message):
    await message.answer("Привет! Это простой бот на aiogram 3.7 😊")

# Запуск
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
