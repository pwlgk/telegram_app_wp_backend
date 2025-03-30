# backend/app/utils/telegram_auth.py
import hashlib
import hmac
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Tuple, Any, List # Добавили List
from urllib.parse import unquote, parse_qsl

# Не импортируем settings напрямую, чтобы избежать циклического импорта,
# если этот модуль понадобится где-то еще до инициализации settings.
# Токен бота будет передаваться как аргумент.
# from app.core.config import settings

logger = logging.getLogger(__name__)

class TelegramAuthError(Exception):
    """Custom exception for Telegram authentication errors."""
    pass

def _parse_value(key: str, value: str) -> Any:
    """
    Вспомогательная функция: декодирует значение из URL-формата
    и парсит JSON для полей 'user', 'receiver', 'chat'.
    """
    decoded_value = unquote(value)
    if key in ('user', 'receiver', 'chat'):
        # Проверяем, что это похоже на JSON, прежде чем парсить
        if decoded_value.startswith('{') and decoded_value.endswith('}'):
            try:
                return json.loads(decoded_value)
            except json.JSONDecodeError:
                logger.warning(f"Failed to decode JSON for key '{key}' in initData: {decoded_value[:100]}...")
                # В случае ошибки парсинга JSON, возвращаем как есть (декодированную строку)
                return decoded_value
        else:
            # Если не похоже на JSON, просто возвращаем декодированную строку
             return decoded_value
    # Для всех остальных ключей просто возвращаем декодированную строку
    return decoded_value

def validate_init_data(
    init_data: str,
    bot_token: str,
    max_age_seconds: int = 3600 # 1 час
) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """
    Валидирует строку initData, полученную от Telegram Web App.

    Сначала проверяет хеш, используя оригинальные значения полей,
    а затем парсит значения для возврата удобного словаря.

    Args:
        init_data: Строка initData (window.Telegram.WebApp.initData).
        bot_token: Секретный токен Telegram бота.
        max_age_seconds: Максимально допустимый возраст данных в секундах.

    Returns:
        Кортеж (is_valid: bool, parsed_data: Optional[Dict]).
        parsed_data содержит расшифрованные и распарсенные данные.
        is_valid=True только если хеш совпал И данные не устарели.
    """
    parsed_data_final: Optional[Dict[str, Any]] = None
    data_pairs_for_check: List[Tuple[str, str]] = [] # Определяем здесь

    try:
        # --- ШАГ 1: Парсинг ОРИГИНАЛЬНОЙ строки для проверки хеша ---
        # parse_qsl сохраняет порядок и не декодирует значения по умолчанию
        original_pairs = parse_qsl(init_data, keep_blank_values=True)

        received_hash: Optional[str] = None
        auth_date_str: Optional[str] = None

        # Отделяем хеш от остальных данных, сохраняя оригинальные пары
        for key, value in original_pairs:
            if key == 'hash':
                received_hash = value
            else:
                data_pairs_for_check.append((key, value))
                if key == 'auth_date':
                    auth_date_str = value

        if received_hash is None:
            raise TelegramAuthError("Hash not found in initData")
        if auth_date_str is None:
             raise TelegramAuthError("auth_date field is missing in initData.")

        logger.debug(f"Received hash: {received_hash}")

        # --- ШАГ 2: Проверка возраста данных ---
        is_outdated = False
        time_diff = -1
        try:
            auth_timestamp = int(auth_date_str)
            current_timestamp = int(datetime.now(timezone.utc).timestamp())
            time_diff = current_timestamp - auth_timestamp

            if time_diff < 0:
                 logger.warning(f"initData auth_date is in the future? Auth: {auth_timestamp}, Now: {current_timestamp}")
                 # Можно считать ошибкой, но для валидации хеша это не важно
            elif time_diff > max_age_seconds:
                logger.warning(f"initData is too old. Age: {time_diff}s, Max allowed: {max_age_seconds}s")
                is_outdated = True # Помечаем как устаревшее
        except (ValueError, TypeError) as e:
            # Если auth_date некорректен, валидацию провести нельзя
            raise TelegramAuthError(f"Invalid auth_date format: {auth_date_str}. Error: {e}")

        logger.debug(f"Auth date check - Diff: {time_diff}s, Max: {max_age_seconds}s. Is outdated: {is_outdated}")

        # --- ШАГ 3: Формирование строки для проверки хеша ---
        # Сортируем ОРИГИНАЛЬНЫЕ пары (кроме hash) по ключу
        sorted_pairs = sorted(data_pairs_for_check, key=lambda item: item[0])
        # Формируем строку из ОРИГИНАЛЬНЫХ пар key=value
        data_check_string_parts = [f"{key}={value}" for key, value in sorted_pairs]
        data_check_string = "\n".join(data_check_string_parts)
        logger.debug(f"Data check string for hash calculation:\n{data_check_string}")

        # --- ШАГ 4: Вычисление хеша ---
        secret_key = hmac.new(b"WebAppData", bot_token.encode('utf-8'), hashlib.sha256).digest()
        calculated_hash = hmac.new(secret_key, data_check_string.encode('utf-8'), hashlib.sha256).hexdigest()
        logger.debug(f"Calculated hash: {calculated_hash}")

        # --- ШАГ 5: Сравнение хешей ---
        hash_match = hmac.compare_digest(calculated_hash, received_hash) # Безопасное сравнение

        # --- ШАГ 6: Формирование итогового словаря (ПОСЛЕ проверки хеша) ---
        # Теперь парсим значения для удобного использования
        parsed_data_final = {}
        for key, value in data_pairs_for_check:
             parsed_data_final[key] = _parse_value(key, value)

        # --- ШАГ 7: Возврат результата ---
        if hash_match:
            if is_outdated:
                logger.warning("initData validation successful (hash matched), but data is outdated.")
                return False, parsed_data_final # Хеш верный, но старый
            else:
                logger.info("initData validation successful.")
                return True, parsed_data_final
        else:
            logger.warning(f"initData validation FAILED! Hash mismatch. Received: {received_hash}, Calculated: {calculated_hash}")
            return False, parsed_data_final # Хеш не совпал, возвращаем данные и флаг False

    except TelegramAuthError as e:
        logger.error(f"Telegram authentication error: {e}")
        # Пытаемся вернуть распарсенные данные, если они были частично получены до ошибки
        if parsed_data_final is None and data_pairs_for_check:
             try:
                 parsed_data_final = {}
                 for key, value in data_pairs_for_check:
                      parsed_data_final[key] = _parse_value(key, value)
             except Exception as parse_exc:
                  logger.error(f"Could not parse data even after auth error: {parse_exc}")
                  parsed_data_final = None # Сбрасываем, если парсинг не удался
        return False, parsed_data_final
    except Exception as e:
        logger.exception(f"Unexpected error during initData validation: {e}")
        return False, None
