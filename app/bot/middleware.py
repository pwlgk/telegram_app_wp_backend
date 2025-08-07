# backend/app/bot/middleware.py
import logging
from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

logger = logging.getLogger(__name__)

class LoggingMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        # Логируем информацию о входящем событии ДО его обработки хендлером
        logger.info(
            f"Dispatcher received an update. "
            f"Event type: {type(event).__name__}, "
            f"User: {data.get('event_from_user').id if data.get('event_from_user') else 'N/A'}"
        )
        
        # Передаем управление дальше по цепочке (другим middleware и хендлерам)
        result = await handler(event, data)
        
        # Этот код выполнится ПОСЛЕ того, как хендлер отработает
        logger.debug("Handler finished processing the event.")
        
        return result