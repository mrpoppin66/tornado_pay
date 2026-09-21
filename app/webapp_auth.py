"""Проверка подписи Telegram.WebApp.initData.

Telegram подписывает данные о пользователе, которые передаются мини-приложению
при открытии (Telegram.WebApp.initData). Backend обязан проверить эту подпись
HMAC-SHA256 по алгоритму из официальной документации Telegram — иначе любой
человек сможет прислать произвольный user_id и выдать себя за кого угодно.

https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
"""
import hmac
import hashlib
import json
import time
from urllib.parse import parse_qsl


def validate_init_data(init_data: str, bot_token: str, max_age_seconds: int = 86400):
    """Проверяет подпись initData и возвращает dict с данными Telegram-пользователя
    (id, username, first_name, ...), либо None, если подпись неверна, данные
    просрочены или не удалось распарсить."""
    if not init_data or not bot_token:
        return None
    try:
        pairs = parse_qsl(init_data, strict_parsing=True, keep_blank_values=True)
    except ValueError:
        return None
    data = dict(pairs)
    received_hash = data.pop("hash", None)
    if not received_hash:
        return None

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(computed_hash, received_hash):
        return None

    if max_age_seconds:
        try:
            auth_date = int(data.get("auth_date", "0"))
        except ValueError:
            return None
        if auth_date <= 0 or (time.time() - auth_date) > max_age_seconds:
            return None

    user_json = data.get("user")
    if not user_json:
        return None
    try:
        user = json.loads(user_json)
    except json.JSONDecodeError:
        return None
    if not isinstance(user, dict) or "id" not in user:
        return None
    return user
