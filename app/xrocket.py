"""Минимальный асинхронный клиент для xRocket Pay API.

Документация: https://pay.xrocket.tg/api
API-ключ выпускается в боте @xRocket: Rocket Pay -> Create App -> API token.

Все запросы идут на https://pay.xrocket.tg/ с заголовком Rocket-Pay-Key.
"""
import hashlib
import hmac
import os

import aiohttp

XROCKET_API_KEY = os.getenv("XROCKET_API_KEY", "")
XROCKET_BASE_URL = os.getenv("XROCKET_BASE_URL", "https://pay.xrocket.tg").rstrip("/")

# Валюта, в которой выставляются счета на пополнение. xRocket поддерживает
# несколько сетей/валют — по умолчанию используем USDT, как и весь остальной
# учёт баланса в боте.
DEPOSIT_CURRENCY = os.getenv("XROCKET_DEPOSIT_CURRENCY", "USDT")

# Через сколько секунд неоплаченный счёт считается просроченным (максимум
# у xRocket — 86400 секунд, т.е. сутки).
DEPOSIT_EXPIRE_SECONDS = int(os.getenv("XROCKET_DEPOSIT_EXPIRE_SECONDS", "1800"))


class XRocketError(Exception):
    """Ошибка API xRocket Pay (не 2xx-ответ или success=false)."""


def is_configured() -> bool:
    return bool(XROCKET_API_KEY)


def _headers():
    return {"Rocket-Pay-Key": XROCKET_API_KEY}


async def create_invoice(amount: float, description: str = "", payload: str = ""):
    """Создаёт счёт на оплату (пополнение баланса) на сумму amount USDT.
    Возвращает dict с полями id, link, status, amount, expiredIn и т.д.
    (см. схему InvoiceDto в OpenAPI xRocket Pay)."""
    if not is_configured():
        raise XRocketError("XROCKET_API_KEY не задан")
    body = {
        "amount": round(float(amount), 4),
        "numPayments": 1,
        "currency": DEPOSIT_CURRENCY,
        "description": description[:1000] if description else None,
        "payload": payload[:4000] if payload else None,
        "expiredIn": DEPOSIT_EXPIRE_SECONDS,
    }
    body = {k: v for k, v in body.items() if v is not None}
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{XROCKET_BASE_URL}/tg-invoices", json=body, headers=_headers(), timeout=aiohttp.ClientTimeout(total=15)
        ) as resp:
            data = await resp.json()
            if resp.status not in (200, 201) or not data.get("success"):
                raise XRocketError(data.get("message") or f"HTTP {resp.status}")
            return data["data"]


async def get_invoice(invoice_id):
    """Возвращает текущее состояние счёта (FullInvoiceDto), включая
    status: active | paid | expired."""
    if not is_configured():
        raise XRocketError("XROCKET_API_KEY не задан")
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{XROCKET_BASE_URL}/tg-invoices/{invoice_id}", headers=_headers(), timeout=aiohttp.ClientTimeout(total=15)
        ) as resp:
            data = await resp.json()
            if resp.status not in (200, 201) or not data.get("success"):
                raise XRocketError(data.get("message") or f"HTTP {resp.status}")
            return data["data"]


def verify_webhook_signature(raw_body: bytes, signature: str) -> bool:
    """Проверяет заголовок rocket-pay-signature: hex HMAC-SHA-256 от тела
    запроса с ключом = SHA-256(API-токен приложения)."""
    if not XROCKET_API_KEY or not signature or not raw_body:
        return False
    secret = hashlib.sha256(XROCKET_API_KEY.encode()).digest()
    expected = hmac.new(secret, raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)

async def get_app_info():
    """Legacy xRocket Pay: информация о приложении, включая balances."""
    if not is_configured(): raise XRocketError("XROCKET_API_KEY не задан")
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{XROCKET_BASE_URL}/app/info", headers=_headers(), timeout=aiohttp.ClientTimeout(total=15)) as resp:
            data=await resp.json(content_type=None)
            if resp.status not in (200,201) or not data.get("success"):
                raise XRocketError(data.get("message") or f"HTTP {resp.status}")
            return data.get("data", data)
