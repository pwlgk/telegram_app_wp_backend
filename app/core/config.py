# backend/app/core/config.py
import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List, Optional
from dotenv import load_dotenv
from pydantic import computed_field # Импортируем для вычисляемого поля

load_dotenv()

class Settings(BaseSettings):
    PROJECT_NAME: str = "WooCommerce Telegram Mini App Backend"
    API_V1_STR: str = "/api/v1"
    LOGGING_LEVEL: str = os.getenv("LOGGING_LEVEL", "INFO") # Пример использования os

    # --- WooCommerce Settings ---
    WOOCOMMERCE_URL: str
    WOOCOMMERCE_KEY: str
    WOOCOMMERCE_SECRET: str
    WOOCOMMERCE_API_VERSION: str = "wc/v3"

    # --- Telegram Settings ---
    TELEGRAM_BOT_TOKEN: str
    TELEGRAM_MANAGER_IDS_STR: str
    MINI_APP_URL: str
    MINI_APP_URL_BOT: str
    API_BASE_URL: Optional[str] = None
    ADMIN_API_KEY: Optional[str] = None
    
    # --- Webhook Settings ---
    WEBHOOK_HOST: Optional[str] = None
    WEBHOOK_PATH: Optional[str] = None
    WEBHOOK_SECRET: Optional[str] = None
    

    # --- Derived/Helper Settings ---
    @property
    def TELEGRAM_MANAGER_IDS(self) -> List[int]:
        """Преобразует строку ID менеджеров в список целых чисел."""
        try:
            # Отступ в 4 пробела
            return [int(uid.strip()) for uid in self.TELEGRAM_MANAGER_IDS_STR.split(',') if uid.strip()]
        except ValueError:
            # Отступ в 4 пробела
            # Логирование или обработка ошибки, если ID некорректны
            print("ERROR: Invalid TELEGRAM_MANAGER_IDS format in .env. Please provide comma-separated integers.")
            return []

    # --- Вычисляемое поле для полного URL вебхука ---
    @computed_field(return_type=Optional[str])
    @property
    def WEBHOOK_URL(self) -> Optional[str]:
        # Отступ в 4 пробела
        if self.WEBHOOK_HOST and self.WEBHOOK_PATH:
            # Отступ в 8 пробелов
            host = self.WEBHOOK_HOST.rstrip('/')
            path = self.WEBHOOK_PATH.lstrip('/')
            return f"{host}/{path}"
        # Отступ в 4 пробела
        return None

    # Настройки для Pydantic Settings
    model_config = SettingsConfigDict(
        env_file='.env',
        env_file_encoding='utf-8',
        case_sensitive=False,
        extra='ignore'
    )

settings = Settings()
# Проверка при старте (опционально, но полезно)
if "dummy" in settings.WOOCOMMERCE_KEY or "dummy" in settings.WOOCOMMERCE_SECRET:
    print("WARNING: WooCommerce API keys seem to be using default dummy values. Please update them in your .env file.")
if "YOUR_BOT_TOKEN" in settings.TELEGRAM_BOT_TOKEN:
    print("WARNING: Telegram Bot Token is not set. Please update it in your .env file.")
if "your-frontend-app-url.com" in settings.MINI_APP_URL:
    print("WARNING: MINI_APP_URL is not set. Please update it in your .env file.")
if not settings.TELEGRAM_MANAGER_IDS:
     print("WARNING: TELEGRAM_MANAGER_IDS list is empty or invalid. Notifications will not be sent.")
