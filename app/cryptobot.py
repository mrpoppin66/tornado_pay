"""Async client for Crypto Pay API (@CryptoBot)."""
import os
import aiohttp

CRYPTO_PAY_API_TOKEN = os.getenv("CRYPTO_PAY_API_TOKEN", "")
CRYPTO_PAY_BASE_URL = os.getenv("CRYPTO_PAY_BASE_URL", "https://pay.crypt.bot/api").rstrip("/")
DEPOSIT_ASSET = os.getenv("CRYPTOBOT_DEPOSIT_ASSET", "USDT")
CHECK_ASSET = os.getenv("CRYPTOBOT_CHECK_ASSET", "USDT")

class CryptoBotError(Exception): pass

def is_configured(): return bool(CRYPTO_PAY_API_TOKEN)
def _headers(): return {"Crypto-Pay-API-Token": CRYPTO_PAY_API_TOKEN}

async def _request(method, endpoint, **kwargs):
    if not is_configured(): raise CryptoBotError("CRYPTO_PAY_API_TOKEN не задан")
    async with aiohttp.ClientSession() as session:
        async with session.request(method, f"{CRYPTO_PAY_BASE_URL}/{endpoint.lstrip('/')}", headers=_headers(), timeout=aiohttp.ClientTimeout(total=20), **kwargs) as r:
            data = await r.json(content_type=None)
            if r.status >= 300 or not data.get("ok"):
                raise CryptoBotError(data.get("error", {}).get("name") if isinstance(data.get("error"), dict) else str(data.get("error") or f"HTTP {r.status}"))
            return data["result"]

async def create_invoice(amount, description="", payload=""):
    body={"asset": DEPOSIT_ASSET, "amount": f"{float(amount):.4f}", "description": description[:1024], "payload": payload[:4096], "allow_comments": False, "allow_anonymous": False}
    return await _request("POST", "createInvoice", json=body)

async def get_invoice(invoice_id):
    result=await _request("GET", "getInvoices", params={"invoice_ids": str(invoice_id)})
    items=result.get("items", [])
    if not items: raise CryptoBotError("Invoice not found")
    return items[0]

async def create_check(amount, user_id=None):
    # Public CryptoBot cheque: do not pin it to a Telegram user.
    # The optional user_id is kept only for backward-compatible callers.
    body={"asset": CHECK_ASSET, "amount": f"{float(amount):.4f}"}
    return await _request("POST", "createCheck", json=body)

async def get_balances():
    """Возвращает балансы приложения Crypto Pay по активам."""
    return await _request("GET", "getBalance")
