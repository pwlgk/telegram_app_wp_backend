# backend/app/main.py
import logging
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, status # Убедимся, что status импортирован
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from app.api.v1.router import api_router_v1
from app.api.v1.endpoints.webhook import router as webhook_router
from app.core.config import settings
from app.services.woocommerce import WooCommerceService # Импорт сервиса
from app.services.telegram import TelegramService     # Импорт сервиса
from app.bot.instance import initialize_bot, shutdown_bot # Функции управления ботом
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter # Импорты исключений

# --- Настройка логирования ---
log_level = settings.LOGGING_LEVEL.upper()
logging.basicConfig(
    level=log_level,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("aiogram").setLevel(logging.INFO)

logger = logging.getLogger(__name__)
logger.info(f"Starting application with log level: {log_level}")


# --- Lifespan для управления ресурсами ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Application startup: Initializing resources...")
    # Инициализация Aiogram Bot и Dispatcher
    bot, dp = await initialize_bot()
    # Инициализация сервисов приложения
    woo_service = WooCommerceService()
    telegram_service = TelegramService(bot=bot)

    # Сохранение экземпляров в состоянии приложения для доступа через зависимости
    app.state.woocommerce_service = woo_service
    app.state.telegram_service = telegram_service
    app.state.bot_instance = bot
    app.state.dispatcher_instance = dp
    logger.info("Services, Bot, and Dispatcher initialized.")

    # --- Установка вебхука при старте ---
    webhook_url = settings.WEBHOOK_URL
    webhook_secret = settings.WEBHOOK_SECRET
    if webhook_url:
        try:
            current_webhook_info = await bot.get_webhook_info()
            # Проверяем, нужно ли обновлять вебхук
            if current_webhook_info.url != webhook_url or \
               getattr(current_webhook_info, 'allowed_updates', None) != dp.resolve_used_update_types():
                 logger.info(f"Current webhook URL '{current_webhook_info.url}' differs or allowed_updates mismatch. Setting new webhook to: {webhook_url}")
                 await bot.set_webhook(
                     url=webhook_url,
                     secret_token=webhook_secret,
                     allowed_updates=dp.resolve_used_update_types(),
                     drop_pending_updates=True # Удаляем старые обновления при смене URL
                 )
                 # Повторная проверка после установки
                 webhook_info = await bot.get_webhook_info()
                 if webhook_info.url == webhook_url:
                     logger.info(f"Telegram webhook successfully set to: {webhook_url}")
                 else:
                     logger.error(f"Failed to set webhook even after attempt. Current info: {webhook_info}")
            else:
                 logger.info(f"Telegram webhook is already correctly set to: {webhook_url}. Skipping setup.")
        except TelegramAPIError as e: # Обработка ошибок API Telegram (включая Flood Control)
             logger.exception(f"Error managing Telegram webhook: {e}")
        except Exception as e: # Обработка других неожиданных ошибок
             logger.exception(f"Unexpected error during webhook setup: {e}")
    else:
        # Логика удаления вебхука, если URL не задан в конфигурации
        logger.warning("Webhook URL not configured. Deleting any existing webhook...")
        try:
            await bot.delete_webhook(drop_pending_updates=True)
            logger.info("Deleted any existing Telegram webhook.")
        except Exception as e:
            logger.error(f"Error deleting existing webhook: {e}")

    # --- Приложение готово к работе ---
    try:
        yield # FastAPI приложение обрабатывает запросы здесь
    finally:
        # --- Код очистки при остановке приложения ---
        logger.info("Application shutdown: Cleaning up resources...")

        # Удаление вебхука
        logger.info("Deleting Telegram webhook...")
        try:
            current_bot = getattr(app.state, 'bot_instance', None)
            if current_bot:
                webhook_info = await current_bot.get_webhook_info()
                if webhook_info.url: # Удаляем только если он был установлен
                     await current_bot.delete_webhook(drop_pending_updates=False) # Не удаляем обновления при штатной остановке
                     logger.info("Telegram webhook deleted.")
                else:
                     logger.info("No active webhook found to delete.")
            else:
                logger.warning("Bot instance not found in app state during shutdown, skipping webhook deletion.")
        except Exception as e:
            logger.error(f"Error deleting webhook during shutdown: {e}")

        # Закрытие HTTP клиента WooCommerce
        logger.info("Closing WooCommerce HTTP client...")
        woo_service_instance = getattr(app.state, 'woocommerce_service', None) # Безопасный доступ
        if woo_service_instance:
             try:
                 await woo_service_instance.close_client()
                 logger.info("WooCommerce HTTP client closed.")
             except Exception as e:
                 logger.error(f"Error closing WooCommerce client: {e}")
        else:
             logger.warning("WooCommerce service not found in app state during shutdown.")

        # Остановка сессии бота
        await shutdown_bot(bot=getattr(app.state, 'bot_instance', None)) # Безопасный доступ

        logger.info("Resources cleaned up successfully.")


# --- Создание экземпляра FastAPI ---
app = FastAPI(
    title=settings.PROJECT_NAME,
    version="1.0.0",
    description="API бэкенд для Telegram Mini App магазина WooCommerce.",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url=f"{settings.API_V1_STR}/openapi.json"
)

# --- Настройка CORS ---
# Убедитесь, что settings.MINI_APP_URL указан корректно
origins = [
    settings.MINI_APP_URL,
    "http://localhost:5173", # Для локальной разработки Vite
    "http://localhost:8080", # Для локальной разработки Vue CLI
    "http://127.0.0.1:5173",
    "http://127.0.0.1:8080",
    "null", # Для некоторых случаев открытия Web App
]
# Важно: Уберите '/' и '#' из URL в origins, если они там есть
origins = [origin.strip('/# ') for origin in origins if origin]

logger.info(f"Allowed CORS origins: {origins}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*", "X-Telegram-Init-Data"],
    expose_headers=["X-WP-TotalPages", "X-WP-Total", "Link"]  
)

# --- Обработчики ошибок ---
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.warning(f"Request validation error: {exc.errors()} for {request.method} {request.url}")
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": "Ошибка валидации входных данных", "errors": exc.errors()},
    )

@app.exception_handler(ValidationError)
async def pydantic_validation_exception_handler(request: Request, exc: ValidationError):
    logger.error(f"Pydantic model validation error: {exc.errors()} for {request.method} {request.url}")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Ошибка валидации данных", "errors": exc.errors()},
    )

@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    logger.exception(f"Unhandled exception: {exc} for {request.method} {request.url}")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Внутренняя ошибка сервера."},
    )

# --- Подключение роутеров ---
app.include_router(api_router_v1, prefix=settings.API_V1_STR)
logger.info(f"Included API router at prefix: {settings.API_V1_STR}")

# Подключение роутера вебхука
if settings.WEBHOOK_PATH:
    app.include_router(webhook_router, tags=["Telegram Webhook"])
    logger.info(f"Included Telegram webhook router at path: {settings.WEBHOOK_PATH}")
else:
    logger.warning("Webhook path not set, skipping webhook router inclusion.")

# --- Корневой эндпоинт ---
@app.get("/", tags=["Root"], summary="Health check")
async def read_root():
    """Простой эндпоинт для проверки работоспособности API."""
    return {"status": "ok", "project": settings.PROJECT_NAME}

# --- Конец файла app/main.py ---
