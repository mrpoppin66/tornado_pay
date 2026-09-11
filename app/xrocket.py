"""xRocket Pay API (Current) client."""
import hashlib, hmac, os, time, uuid
import aiohttp

# XROCKET_API_TOKEN is preferred. XROCKET_API_KEY is kept as a compatibility alias.
XROCKET_API_TOKEN = os.getenv("XROCKET_API_TOKEN") or os.getenv("XROCKET_API_KEY", "")
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
                msg = data.get("detail") or data.get("message") or data.get("title") or f"HTTP {r.status}"
                raise XRocketError(str(msg))
            return data

def _normalize_invoice(x):
    if not isinstance(x, dict): return x
    links=x.get("links") or {}
    return {**x, "id": x.get("invoiceId", x.get("id")), "link": links.get("telegramBotLink") or x.get("link") or x.get("url")}

async def create_invoice(amount, description="", payload=""):
    body={"amount": f"{float(amount):.4f}", "asset": DEPOSIT_CURRENCY,
          "description": description[:1000], "clientInvoiceId": f"tp-{uuid.uuid4().hex}"}
    # Current API uses callback.payload for correlation. Expires field is intentionally omitted
    # until the API's application defaults are used.
    if payload: body["callback"]={"payload": payload}
    data=await _request("POST", "/api/v1/invoices", json=body)
    return _normalize_invoice(data)

async def get_invoice(invoice_id):
    return _normalize_invoice(await _request("GET", "/api/v1/invoice", params={"invoiceId": str(invoice_id)}))

async def get_balances():
    data=await _request("GET", "/api/v1/balances")
    return data.get("items", data.get("balances", data if isinstance(data,list) else []))

async def get_app_info(): return await _request("GET", "/api/v1/app-info")

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
