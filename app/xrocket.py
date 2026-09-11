"""xRocket Pay API (Current) client."""
import hashlib, hmac, os, time, uuid
import aiohttp

# XROCKET_API_TOKEN is preferred. XROCKET_API_KEY is kept as a compatibility alias.
XROCKET_API_TOKEN = os.getenv("XROCKET_API_TOKEN", "").strip()
XROCKET_WEBHOOK_SECRET = os.getenv("XROCKET_WEBHOOK_SECRET", "")
XROCKET_BASE_URL = os.getenv("XROCKET_BASE_URL", "https://pay.api.xrocket.exchange").rstrip("/")
DEPOSIT_CURRENCY = os.getenv("XROCKET_DEPOSIT_CURRENCY", "USDT")
DEPOSIT_EXPIRE_SECONDS = int(os.getenv("XROCKET_DEPOSIT_EXPIRE_SECONDS", "1800"))

class XRocketError(Exception): pass

def is_configured(): return bool(XROCKET_API_TOKEN)
def _headers(): return {"Authorization": f"Bearer {XROCKET_API_TOKEN}", "Accept":"application/json", "Content-Type":"application/json"}

async def _request(method, path, *, json=None, params=None):
    if not is_configured(): raise XRocketError("XROCKET_API_TOKEN не задан")
    async with aiohttp.ClientSession() as s:
        async with s.request(method, f"{XROCKET_BASE_URL}{path}", headers=_headers(), json=json, params=params, timeout=aiohttp.ClientTimeout(total=20)) as r:
            try: data=await r.json(content_type=None)
            except Exception: data={"detail": await r.text()}
            if not 200 <= r.status < 300:
                msg = (
                    data.get("detail")
                    or data.get("message")
                    or data.get("title")
                    or data.get("type")
                    or f"HTTP {r.status}"
                )
                problem_type = data.get("type")
                kind = data.get("kind")
                instance = data.get("instance")
                parts = [str(msg)]
                if problem_type and problem_type != msg:
                    parts.append(f"type={problem_type}")
                if kind:
                    parts.append(f"kind={kind}")
                if instance:
                    parts.append(f"instance={instance}")
                raise XRocketError(f"HTTP {r.status}: " + " | ".join(parts))
            return data

def _normalize_invoice(x):
    if not isinstance(x, dict):
        return x
    links = x.get("links") or {}
    # Current Pay API returns the invoice object directly.
    # Keep a small compatibility layer for deployments that may still return
    # invoiceId/link-style fields.
    return {
        **x,
        "id": x.get("id", x.get("invoiceId")),
        "link": (
            links.get("telegramBotLink")
            or x.get("link")
            or x.get("url")
            or ""
        ),
    }

async def create_invoice(amount, description="", payload=""):
    # Current xRocket Pay API uses priceAmount/priceCurrency.
    # The old Legacy names amount/asset cause:
    # "The provided data failed validation".
    body = {
        "priceAmount": f"{float(amount):.4f}",
        "priceCurrency": DEPOSIT_CURRENCY,
        "description": description[:1000],
        "clientInvoiceId": f"tp-{uuid.uuid4().hex}",
        "expiresIn": DEPOSIT_EXPIRE_SECONDS,
    }
    if payload:
        body["callback"] = {"payload": {"userId": str(payload)}}
    data = await _request("POST", "/api/v1/invoices", json=body)
    return _normalize_invoice(data)

async def get_invoice(invoice_id):
    # Current invoice IDs are strings; do not cast them to int.
    return _normalize_invoice(
        await _request("GET", "/api/v1/invoice", params={"invoiceId": str(invoice_id)})
    )

async def get_invoice_payments(invoice_id):
    data = await _request(
        "GET", "/api/v1/invoice/payments",
        params={"invoiceId": str(invoice_id)}
    )
    return data.get("items", data.get("payments", data if isinstance(data, list) else []))

async def get_balances():
    data=await _request("GET", "/api/v1/balances")
    return data.get("items", data.get("balances", data if isinstance(data,list) else []))

async def get_app_info(): return await _request("GET", "/api/v1/app-info")

async def create_cheque(amount, telegram_user_id, description="", client_cheque_id=None):
    """Create a personal xRocket cheque for a Telegram user.

    The current Pay API reserves the amount from the application balance and
    returns an activation link. The cheque is addressed to the Telegram user,
    so the executor does not need to provide a blockchain address.
    """
    cid = client_cheque_id or f"tp-wd-{uuid.uuid4().hex}"
    body = {
        "asset": "USDT",
        "amount": f"{float(amount):.4f}",
        "targetType": "telegram_user_id",
        "target": str(telegram_user_id),
        "clientChequeId": cid,
        "description": (description or "TornadoPay withdrawal")[:1000],
    }
    data = await _request("POST", "/api/v1/cheques", json=body)
    links = data.get("links") or {}
    data["id"] = data.get("chequeId", data.get("id"))
    data["link"] = links.get("telegramMiniAppLink") or data.get("url") or ""
    data["clientChequeId"] = data.get("clientChequeId", cid)
    return data

async def get_cheque(cheque_id=None, client_cheque_id=None):
    params = {}
    if cheque_id:
        params["chequeId"] = str(cheque_id)
    if client_cheque_id:
        params["clientChequeId"] = str(client_cheque_id)
    if not params:
        raise XRocketError("Не указан chequeId или clientChequeId")
    data = await _request("GET", "/api/v1/cheque", params=params)
    if isinstance(data, dict):
        links = data.get("links") or {}
        data["id"] = data.get("chequeId", data.get("id"))
        data["link"] = links.get("telegramMiniAppLink") or data.get("url") or data.get("link") or ""
    return data

async def create_payout(amount, telegram_user_id, description="", client_payout_id=None):
    """Send an immediate xRocket Pay payout directly to a Telegram user.

    Unlike a personal cheque, a payout is settled inside the POST request and
    does not require the recipient to open/claim anything. The Pay API accepts
    telegram_user_id as the target type and resolves it to the recipient's
    internal xRocket user ID.
    """
    cid = client_payout_id or f"tp-wd-{uuid.uuid4().hex}"
    body = {
        "asset": "USDT",
        "amount": f"{float(amount):.4f}",
        "targetType": "telegram_user_id",
        "target": str(telegram_user_id),
        "clientPayoutId": cid,
        "description": (description or "TornadoPay withdrawal")[:1000],
    }
    data = await _request("POST", "/api/v1/payouts", json=body)
    if not isinstance(data, dict):
        raise XRocketError("xRocket вернул некорректный ответ на payout")
    data["id"] = data.get("payoutId", data.get("id"))
    data["clientPayoutId"] = data.get("clientPayoutId", cid)
    return data

async def get_payout(payout_id=None, client_payout_id=None):
    params = {}
    if payout_id:
        params["payoutId"] = str(payout_id)
    if client_payout_id:
        params["clientPayoutId"] = str(client_payout_id)
    if not params:
        raise XRocketError("Не указан payoutId или clientPayoutId")
    data = await _request("GET", "/api/v1/payout", params=params)
    if isinstance(data, dict):
        data["id"] = data.get("payoutId", data.get("id"))
    return data

async def create_withdrawal(amount, address, network):
    body={"amount":f"{float(amount):.4f}", "asset":"USDT", "network":network,
          "address":address, "clientWithdrawalId":f"tp-cash-{uuid.uuid4().hex}"}
    return await _request("POST", "/api/v1/withdrawals", json=body)

def verify_webhook_signature(raw_body, signature, timestamp=None, version=None):
    # Current Pay API signature. Legacy fallback is intentionally available only when
    # no webhook secret has been configured, so existing deployments can migrate.
    if not signature or not raw_body: return False
    if timestamp and XROCKET_WEBHOOK_SECRET:
        if version and version != "v1": return False
        try:
            if abs(time.time()*1000-int(timestamp)) > 5*60*1000: return False
        except Exception: return False
        expected=hmac.new(XROCKET_WEBHOOK_SECRET.encode(), f"{timestamp}.".encode()+raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)
    if XROCKET_API_TOKEN:
        secret=hashlib.sha256(XROCKET_API_TOKEN.encode()).digest()
        expected=hmac.new(secret, raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)
    return False
