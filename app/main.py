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
from app.bot.utils import set_bot_commands # <<< ИМПОРТИРУЕМ ФУНКЦИЮ
from filelock import FileLock, Timeout # <<< Добавляем импорт

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
    # Эти операции безопасны для запуска в нескольких процессах
    bot, dp = await initialize_bot()
    woo_service = WooCommerceService()
    telegram_service = TelegramService(bot=bot)

    # Сохраняем экземпляры в состоянии приложения
    app.state.woocommerce_service = woo_service
    app.state.telegram_service = telegram_service
    app.state.bot_instance = bot
    app.state.dispatcher_instance = dp
    logger.info("Services, Bot, and Dispatcher initialized in current worker.")

    # --- БЛОК ОДНОРАЗОВОЙ ИНИЦИАЛИЗАЦИИ ---
    # Создаем lock-файл во временной директории
    lock = FileLock("app_startup.lock", timeout=10) # Таймаут 10 секунд на захват

    try:
        # Пытаемся захватить блокировку. Только один воркер сможет это сделать.
        with lock:
            logger.info("Lock acquired by this worker. Performing one-time setup...")
            
            # 1. Устанавливаем команды бота
            await set_bot_commands(bot)

            # 2. Устанавливаем вебхук
            webhook_url = settings.WEBHOOK_URL
            webhook_secret = settings.WEBHOOK_SECRET
            if webhook_url:
                try:
                    current_webhook_info = await bot.get_webhook_info()
                    if current_webhook_info.url != webhook_url:
                        logger.info(f"Setting new webhook to: {webhook_url}")
                        await bot.set_webhook(
                            url=webhook_url,
                            secret_token=webhook_secret,
                            allowed_updates=dp.resolve_used_update_types(),
                            drop_pending_updates=True
                        )
                        logger.info(f"Telegram webhook successfully set.")
                    else:
                        logger.info(f"Telegram webhook is already set correctly. Skipping.")
                except TelegramAPIError as e:
                    logger.exception(f"Error managing Telegram webhook: {e}")
                except Exception as e:
                    logger.exception(f"Unexpected error during webhook setup: {e}")
            else:
                logger.warning("Webhook URL not configured. Deleting any existing webhook...")
                await bot.delete_webhook(drop_pending_updates=True)
            
            logger.info("One-time setup complete. Releasing lock.")

    except Timeout:
        # Этот блок выполнится для всех остальных воркеров, которые не смогли захватить лок
        logger.info("Could not acquire lock, another worker is performing setup. Skipping.")

    # --- КОНЕЦ БЛОКА ОДНОРАЗОВОЙ ИНИЦИАЛИЗАЦИИ ---

    try:
        yield
    finally:
        logger.info("Application shutdown in this worker: Cleaning up resources...")
        
        # Очистка ресурсов при остановке каждого воркера
        await woo_service.close_client()
        await shutdown_bot(bot=app.state.bot_instance)

        # Удаление вебхука при остановке также должно быть защищено
        try:
            with lock:
                logger.info("Lock acquired for shutdown. Deleting webhook...")
                current_bot = getattr(app.state, 'bot_instance', None)
                if current_bot:
                    await current_bot.delete_webhook(drop_pending_updates=False)
                    logger.info("Telegram webhook deleted by this worker.")
        except Timeout:
            logger.info("Could not acquire lock for shutdown, another worker will handle it. Skipping.")
        except Exception as e:
            logger.error(f"Error deleting webhook during shutdown: {e}")

        logger.info("Resources cleaned up successfully in this worker.")

        
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
