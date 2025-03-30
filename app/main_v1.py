# backend/app/main.py
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from app.api.v1.router import api_router_v1 # Импортируем роутер v1
from app.core.config import settings
from app.services.woocommerce import WooCommerceService
from app.services.telegram import TelegramService
from app.bot.instance import initialize_bot, shutdown_bot # Функции управления ботом

# --- Настройка логирования ---
# Устанавливаем уровень из конфига
log_level = settings.LOGGING_LEVEL.upper()
logging.basicConfig(
    level=log_level,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
# Уменьшаем шум от uvicorn и httpx на уровне INFO
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)
logger.info(f"Starting application with log level: {log_level}")


# --- Lifespan для управления ресурсами ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Application startup: Initializing resources...")
    # Инициализация бота Aiogram
    bot, dp = await initialize_bot()
    # Инициализация сервисов
    woo_service = WooCommerceService()
    telegram_service = TelegramService(bot=bot)

    # Сохраняем экземпляры в состоянии приложения для доступа через зависимости
    app.state.woocommerce_service = woo_service
    app.state.telegram_service = telegram_service
    app.state.bot_instance = bot # Сохраняем и бота, если понадобится напрямую
    app.state.dispatcher_instance = dp

    logger.info("WooCommerce service, Telegram service, Bot, and Dispatcher initialized.")

    yield # Приложение работает здесь

    # Код, выполняемый при остановке приложения
    logger.info("Application shutdown: Cleaning up resources...")
    # Закрываем HTTP клиент WooCommerce
    await woo_service.close_client()
    # Корректно останавливаем бота
    await shutdown_bot(bot=app.state.bot_instance)
    logger.info("Resources cleaned up successfully.")

# --- Создание экземпляра FastAPI ---
app = FastAPI(
    title=settings.PROJECT_NAME,
    version="1.0.0",
    description="API бэкенд для Telegram Mini App магазина WooCommerce.",
    lifespan=lifespan, # Подключаем lifespan
    # Документация API будет доступна по /docs и /redoc
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url=f"{settings.API_V1_STR}/openapi.json" # Путь к OpenAPI схеме
)

# --- Настройка CORS ---
# !!! ВАЖНО: Укажите правильные URL вашего фронтенда !!!
origins = [
    # URL развернутого фронтенда (обязательно!)
    settings.MINI_APP_URL,
    # URL для локальной разработки фронтенда (замените порт при необходимости)
    "http://localhost:5173", # Стандартный порт Vite
    "http://localhost:8080", # Стандартный порт Vue CLI
    "http://127.0.0.1:5173",
    "http://127.0.0.1:8080",
    # Иногда Telegram Web Apps могут приходить с origin "null"
    "null",
]
logger.info(f"Allowed CORS origins: {origins}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True, # Разрешить куки/заголовки авторизации
    allow_methods=["*"], # Разрешить все методы (GET, POST, PUT, OPTIONS и т.д.)
    allow_headers=["*", "X-Telegram-Init-Data"], # Разрешить все стандартные и наш кастомный заголовок
)

# --- Обработчики ошибок (глобальные) ---
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    # Более подробное логирование ошибок валидации Pydantic
    logger.warning(f"Request validation error: {exc.errors()} for {request.method} {request.url}")
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": "Ошибка валидации входных данных", "errors": exc.errors()},
    )

@app.exception_handler(ValidationError) # Ошибки валидации Pydantic внутри кода
async def pydantic_validation_exception_handler(request: Request, exc: ValidationError):
    logger.error(f"Pydantic model validation error: {exc.errors()} for {request.method} {request.url}")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Ошибка валидации данных", "errors": exc.errors()},
    )

@app.exception_handler(Exception) # Обработчик для всех остальных исключений
async def generic_exception_handler(request: Request, exc: Exception):
    logger.exception(f"Unhandled exception: {exc} for {request.method} {request.url}") # Логируем с traceback
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Внутренняя ошибка сервера."},
    )

# --- Подключение роутеров API ---
app.include_router(api_router_v1, prefix=settings.API_V1_STR)
logger.info(f"Included API router at prefix: {settings.API_V1_STR}")

# --- Корневой эндпоинт для проверки ---
@app.get("/", tags=["Root"], summary="Health check")
async def read_root():
    """Простой эндпоинт для проверки работоспособности API."""
    return {"status": "ok", "project": settings.PROJECT_NAME}

# --- Запуск приложения (для локальной разработки) ---
# Обычно используется команда: uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
# if __name__ == "__main__":
#     import uvicorn
#     logger.info("Starting Uvicorn server for local development...")
#     uvicorn.run(
#         "app.main:app",
#         host="0.0.0.0",
#         port=8000,
#         reload=True, # Включить автоперезагрузку при изменении кода
#         log_level=settings.LOGGING_LEVEL.lower() # Передаем уровень логирования uvicorn
#     )