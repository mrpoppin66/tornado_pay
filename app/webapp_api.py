"""REST API для Telegram Mini App.

Полностью переиспользует бизнес-логику из db.py / xrocket.py / cryptobot.py —
ту же самую, что использует чат-бот. Ни один расчёт (курс, комиссии, эскроу,
рефералка, тайм-ауты) не продублирован: миниапп и бот всегда работают с
одними и теми же данными и правилами, поэтому пользователь может свободно
переключаться между чатом и приложением.

Аутентификация — через Telegram.WebApp.initData (см. webapp_auth.py):
подпись проверяется на каждый запрос под /api/, отдельного логина не нужно.
"""
import io
import os
import re
from datetime import datetime, date
from decimal import Decimal
from html import escape as html_escape

from aiohttp import web
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from . import xrocket
from . import cryptobot
from .webapp_auth import validate_init_data
from .db import (
    ensure_user, get_user, get_user_agreement_accepted, accept_user_agreement,
    get_services, get_service, create_order, get_orders,
    get_exchange_rate,
    get_available_executors, get_free_orders, claim_order,
    complete_executor_order, confirm_order_by_client, dispute_order_by_client,
    get_executor_orders, get_executor_active_order, get_executor_history,
    get_executor_detailed_stats, set_executor_available, set_executor_notify_enabled,
    get_active_executor_application, get_latest_executor_application,
    create_executor_application, answer_executor_application,
    submit_order_rating, has_rating,
    get_order_chat_peer, save_order_chat_message, get_order_chat_messages_after,
    get_recent_chat_messages,
    get_order,
    get_user_transactions,
    create_deposit, mark_deposit_paid,
    create_withdrawal_request, set_withdrawal_provider, approve_withdrawal, mark_withdrawal_error,
    get_payment_settings, is_payment_provider_enabled, get_payment_min_amount, PAYMENT_PROVIDER_LABELS,
    get_referral_settings, get_referral_stats, credit_referral_order_commission,
    get_notifications, get_unread_notifications_count, mark_notifications_read,
    log_order_event, create_notification,
)
from .admin import get_admin_ids


class ApiError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


# ---------- JSON-сериализация asyncpg Record / Decimal / datetime ----------

def jsonable(value):
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def row_to_dict(row):
    if row is None:
        return None
    return jsonable(dict(row))


def rows_to_list(rows):
    return [row_to_dict(r) for r in rows]


# ---------- Middleware: аутентификация и единый формат ошибок ----------

@web.middleware
async def api_middleware(request: web.Request, handler):
    if not request.path.startswith("/api/"):
        return await handler(request)
    try:
        init_data = request.headers.get("X-Telegram-Init-Data", "")
        bot_token = request.app["bot_token"]
        tg_user = validate_init_data(init_data, bot_token)
        if not tg_user:
            return web.json_response({"error": "unauthorized"}, status=401)
        request["tg_user"] = tg_user
        request["uid"] = int(tg_user["id"])
        return await handler(request)
    except ApiError as e:
        return web.json_response({"error": e.message}, status=e.status)
    except web.HTTPException:
        raise
    except Exception as e:
        print(f"[webapp api] unhandled error at {request.path}: {e}")
        return web.json_response({"error": "internal_error"}, status=500)


async def _json_body(request):
    try:
        return await request.json()
    except Exception:
        raise ApiError("Некорректный формат запроса (ожидается JSON)")


# ---------- Профиль / бутстрап ----------

async def api_me(request: web.Request):
    uid = request["uid"]
    tg_user = request["tg_user"]
    await ensure_user(uid, tg_user.get("username"))
    u = await get_user(uid)
    if not u:
        raise ApiError("Пользователь не найден", status=404)
    agreement_accepted = await get_user_agreement_accepted(uid)
    app_row = await get_latest_executor_application(uid)
    payment_settings = await get_payment_settings()
    referral_settings = await get_referral_settings()
    admin_ids = await get_admin_ids()
    data = row_to_dict(u)
    data.update({
        "agreement_accepted": agreement_accepted,
        "is_admin": uid in admin_ids,
        "executor_application": row_to_dict(app_row),
        "exchange_rate": get_exchange_rate(),
        "payment_settings": {
            "cryptobot": {
                "configured": cryptobot.is_configured(),
                "deposit_enabled": payment_settings["cryptobot_deposit_enabled"],
                "withdraw_enabled": payment_settings["cryptobot_withdraw_enabled"],
                "min_deposit": payment_settings["cryptobot_min_deposit"],
                "min_withdraw": payment_settings["cryptobot_min_withdraw"],
            },
            "xrocket": {
                "configured": xrocket.is_configured(),
                "deposit_enabled": payment_settings["xrocket_deposit_enabled"],
                "withdraw_enabled": payment_settings["xrocket_withdraw_enabled"],
                "min_deposit": payment_settings["xrocket_min_deposit"],
                "min_withdraw": payment_settings["xrocket_min_withdraw"],
            },
        },
        "referral_settings": {
            "percent": referral_settings["percent"],
            "flat_bonus": referral_settings["flat_bonus"],
        },
    })
    return web.json_response(jsonable(data))


async def api_agreement_accept(request: web.Request):
    await accept_user_agreement(request["uid"])
    return web.json_response({"ok": True})


# ---------- Услуги и заявки (клиент) ----------

async def api_services(request: web.Request):
    rows = await get_services()
    return web.json_response(rows_to_list(rows))


ORDER_CREATE_ERROR_MESSAGES = {
    "service_not_found": "Услуга не найдена или временно отключена.",
    "below_minimum": "Сумма меньше минимальной для этой услуги.",
    "above_maximum": "Сумма больше максимальной для этой услуги.",
    "user_not_found": "Пользователь не найден.",
    "insufficient_balance": "Недостаточно средств на балансе.",
}


MAX_QR_DATA_URL_LEN = 900_000  # ограничение на размер встроенного base64-изображения QR


MOBILE_OPERATORS = ["МТС", "МегаФон", "Билайн", "Т2", "Йота", "Добросвязь"]


def _is_mobile_topup(service_name):
    return "мобиль" in str(service_name or "").lower()


def _parse_webapp_payment_details(payment_type, service_name, body):
    """Валидирует и нормализует реквизиты, присланные из Mini App, по аналогии
    с проверкой в чат-боте (см. bot.py: _validate_payment_details)."""
    if payment_type == "card":
        raw = str(body.get("payment_details") or "")
        digits = re.sub(r"\D", "", raw)
        if not (13 <= len(digits) <= 19):
            raise ApiError("Введите корректный номер карты (13–19 цифр).")
        return "card", digits, None

    if payment_type == "qr":
        method = body.get("payment_method")
        raw = body.get("payment_details")
        if method == "qr_link":
            value = str(raw or "").strip()
            if not re.match(r"^https?://\S+$", value, re.IGNORECASE):
                raise ApiError("Введите корректную ссылку на оплату (начинается с http:// или https://).")
            return "qr_link", value, None
        if method == "qr_photo_data":
            value = str(raw or "")
            if not value.startswith("data:image/"):
                raise ApiError("Загрузите фото QR-кода.")
            if len(value) > MAX_QR_DATA_URL_LEN:
                raise ApiError("Изображение QR-кода слишком большое. Попробуйте другое фото.")
            return "qr_photo_data", value, None
        raise ApiError("Укажите ссылку на оплату или загрузите фото QR-кода.")

    # phone (в т.ч. "Пополнение мобильного" и "СБП") — реквизит по умолчанию.
    raw = str(body.get("payment_details") or "").strip()
    digits = re.sub(r"\D", "", raw)
    if not (7 <= len(digits) <= 15):
        raise ApiError("Введите корректный номер телефона (7–15 цифр).")
    if _is_mobile_topup(service_name):
        operator = str(body.get("payment_operator") or "").strip()
        if not operator:
            raise ApiError("Выберите оператора.")
        if len(operator) > 60:
            raise ApiError("Слишком длинное название оператора.")
        raw = f"{raw} ({operator})"
    return "phone", raw, None


async def api_orders_create(request: web.Request):
    uid = request["uid"]
    if not await get_user_agreement_accepted(uid):
        raise ApiError("Сначала нужно принять пользовательское соглашение.", status=403)
    body = await _json_body(request)
    try:
        service_id = int(body.get("service_id"))
        amount_rub = float(body.get("amount_rub"))
    except (TypeError, ValueError):
        raise ApiError("Некорректные параметры заявки.")
    comment = str(body.get("comment") or "")[:500]

    service = await get_service(service_id)
    if not service or not service["active"]:
        raise ApiError(ORDER_CREATE_ERROR_MESSAGES["service_not_found"])
    payment_type = service["payment_type"]

    payment_method = payment_details = payment_file_id = None
    if payment_type in ("card", "phone", "qr"):
        payment_method, payment_details, payment_file_id = _parse_webapp_payment_details(payment_type, service["name"], body)

    order_id, reason = await create_order(
        uid, service_id, amount_rub,
        payment_method=payment_method, payment_details=payment_details, payment_file_id=payment_file_id,
        order_comment=comment,
    )
    if not order_id:
        raise ApiError(ORDER_CREATE_ERROR_MESSAGES.get(reason, reason))
    await log_order_event(order_id, uid, "created", "Заявка создана через Mini App")
    bot = request.app["bot"]
    executors = await get_available_executors()
    order_row = await get_order(order_id)
    comment_line = f"\nКомментарий: <b>{html_escape(comment)}</b>" if comment else ""
    text = (
        f"🆕 <b>Новая заявка #{order_id}</b>\n\n"
        f"Услуга: <b>{html_escape(service['name'])}</b>\n"
        f"Переводите: <b>{amount_rub:.2f} RUB</b> → получите: <b>{float(order_row['executor_commission_amount']) + float(order_row['user_amount_usdt']):.4f} USDT</b>"
        f"{comment_line}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="👀 Открыть заявку", callback_data=f"exec:order:{order_id}")]])
    for row in executors:
        try:
            await bot.send_message(row[0], text, reply_markup=kb, parse_mode="HTML")
        except Exception as e:
            print(f"[webapp new order notify] {row[0]}: {e}")
    return web.json_response({"ok": True, "order_id": order_id})


async def api_orders_list(request: web.Request):
    uid = request["uid"]
    role = request.query.get("role", "client")
    if role == "executor":
        status = request.query.get("status") or None
        rows = await get_executor_orders(uid, status=status)
    else:
        rows = await get_orders(uid)
    return web.json_response(rows_to_list(rows))


async def _load_order_for_participant(order_id, uid):
    order = await get_order(order_id)
    if not order or (order["user_id"] != uid and order["executor_id"] != uid):
        raise ApiError("Заявка не найдена или недоступна.", status=404)
    return order


async def api_order_detail(request: web.Request):
    uid = request["uid"]
    order_id = int(request.match_info["order_id"])
    order = await _load_order_for_participant(order_id, uid)
    data = row_to_dict(order)
    data["is_client"] = order["user_id"] == uid
    data["is_executor"] = order["executor_id"] == uid
    peer = await get_order_chat_peer(order_id, uid)
    data["chat_open"] = bool(peer)
    messages = await get_recent_chat_messages(order_id, limit=50)
    data["chat_messages"] = list(reversed(rows_to_list(messages)))
    data["rated"] = (await has_rating(order_id, uid)) if data["is_client"] else None
    return web.json_response(jsonable(data))


async def api_order_qr_image(request: web.Request):
    """Отдаёт фото QR-кода заявки, если оно было отправлено через чат-бота
    (хранится как Telegram file_id) — для заявок, созданных через Mini App,
    QR уже встроен в payment_details как data:-URL и этот эндпоинт не нужен."""
    uid = request["uid"]
    order_id = int(request.match_info["order_id"])
    order = await _load_order_for_participant(order_id, uid)
    if order["payment_method"] != "qr_photo" or not order["payment_file_id"]:
        raise ApiError("QR-код недоступен.", status=404)
    bot = request.app["bot"]
    buf = io.BytesIO()
    try:
        await bot.download(order["payment_file_id"], destination=buf)
    except Exception as e:
        print(f"[webapp qr image] {e}")
        raise ApiError("Не удалось загрузить QR-код.", status=502)
    buf.seek(0)
    return web.Response(body=buf.read(), content_type="image/jpeg")


async def api_order_claim(request: web.Request):
    uid = request["uid"]
    order_id = int(request.match_info["order_id"])
    client_id, reason = await claim_order(order_id, uid)
    if reason != "ok":
        messages = {
            "unavailable": "Сейчас вы не можете брать заявки (недоступны, заблокированы или не исполнитель).",
            "active_exists": "У вас уже есть активная заявка — сначала завершите её.",
            "not_found": "Заявка не найдена.",
            "already_taken": "Заявка уже взята другим исполнителем.",
            "own_order": "Нельзя взять собственную заявку.",
        }
        raise ApiError(messages.get(reason, reason))
    await log_order_event(order_id, uid, "claimed", "Заявка взята в работу через Mini App")
    await create_notification(client_id, "order", f"👷 Исполнитель найден по заявке #{order_id}", "Исполнитель принял вашу заявку.", order_id)
    bot = request.app["bot"]
    try:
        await bot.send_message(
            client_id,
            f"👷 <b>Исполнитель найден</b>\n\nВаша заявка #{order_id} принята исполнителем.\nТеперь вы можете общаться через анонимный чат TornadoPay.",
            parse_mode="HTML",
        )
    except Exception as e:
        print(f"[webapp claim notify] {e}")
    return web.json_response({"ok": True})


async def api_order_complete(request: web.Request):
    uid = request["uid"]
    order_id = int(request.match_info["order_id"])
    client_id = await complete_executor_order(order_id, uid)
    if not client_id:
        raise ApiError("Заявка недоступна для завершения.")
    await log_order_event(order_id, uid, "completed_by_executor", "Исполнитель отметил заявку выполненной (Mini App)")
    await create_notification(client_id, "order", f"⏳ Заявка #{order_id} отмечена выполненной", "Проверьте результат и подтвердите либо откройте спор.", order_id)
    bot = request.app["bot"]
    try:
        await bot.send_message(
            client_id,
            f"⏳ <b>Заявка #{order_id} отмечена выполненной.</b>\n\nПроверьте результат и подтвердите выполнение либо откройте спор.",
            parse_mode="HTML",
        )
    except Exception as e:
        print(f"[webapp complete notify] {e}")
    return web.json_response({"ok": True})


async def api_order_confirm(request: web.Request):
    uid = request["uid"]
    order_id = int(request.match_info["order_id"])
    result = await confirm_order_by_client(order_id, uid)
    if not result:
        raise ApiError("Заявка уже обработана или недоступна.")
    executor_id, payout = result
    await log_order_event(order_id, uid, "confirmed", "Клиент подтвердил выполнение (Mini App)")
    await create_notification(executor_id, "order", f"✅ Заявка #{order_id} завершена", "Клиент подтвердил выполнение.", order_id)
    bot = request.app["bot"]
    try:
        await bot.send_message(executor_id, f"🎉 <b>Заявка #{order_id} подтверждена клиентом.</b>\n\nСредства за заявку зачислены на ваш баланс.", parse_mode="HTML")
    except Exception as e:
        print(f"[webapp confirm notify] {e}")
    referral_result = await credit_referral_order_commission(order_id)
    if referral_result:
        try:
            await bot.send_message(
                referral_result["referrer_id"],
                f"🤝 <b>Реферальное вознаграждение</b>\n\nНачислено <b>{referral_result['amount']:.4f} USDT</b> за заявку вашего реферала #{order_id}.",
                parse_mode="HTML",
            )
        except Exception as e:
            print(f"[webapp referral notify] {e}")
    return web.json_response({"ok": True, "payout": payout})


async def api_order_dispute(request: web.Request):
    uid = request["uid"]
    order_id = int(request.match_info["order_id"])
    executor_id = await dispute_order_by_client(order_id, uid)
    if executor_id is None:
        raise ApiError("Заявка уже обработана или недоступна.")
    await log_order_event(order_id, uid, "dispute_opened", "Клиент открыл спор (Mini App)")
    await create_notification(executor_id, "dispute", f"⚖️ Спор по заявке #{order_id}", "Клиент открыл спор.", order_id)
    bot = request.app["bot"]
    try:
        await bot.send_message(executor_id, f"⚠️ <b>По заявке #{order_id} открыт спор.</b>\n\nСредства остаются в резерве до решения администрации.", parse_mode="HTML")
    except Exception as e:
        print(f"[webapp dispute notify] {e}")
    for admin_id in await get_admin_ids():
        try:
            await bot.send_message(
                admin_id,
                f"⚠️ <b>Открыт спор по заявке #{order_id}</b>\n\nКлиент: <code>{uid}</code>\nИсполнитель: <code>{executor_id}</code>",
                parse_mode="HTML",
            )
        except Exception as e:
            print(f"[webapp dispute admin notify] {e}")
    return web.json_response({"ok": True})


async def api_order_rate(request: web.Request):
    uid = request["uid"]
    order_id = int(request.match_info["order_id"])
    body = await _json_body(request)
    try:
        stars = int(body.get("stars"))
    except (TypeError, ValueError):
        raise ApiError("Оценка должна быть числом от 1 до 5.")
    if stars < 1 or stars > 5:
        raise ApiError("Оценка должна быть от 1 до 5.")
    executor_id, ok, reason = await submit_order_rating(order_id, uid, stars)
    if not ok:
        messages = {
            "not_found": "Заявка не найдена.", "not_owner": "Это не ваша заявка.",
            "no_executor": "У заявки нет исполнителя.", "not_done": "Заявка ещё не завершена.",
            "already_rated": "Вы уже оценили эту заявку.",
        }
        raise ApiError(messages.get(reason, reason))
    bot = request.app["bot"]
    try:
        await bot.send_message(executor_id, f"⭐ Вы получили оценку {stars}/5 по заявке #{order_id}.")
    except Exception:
        pass
    return web.json_response({"ok": True})


# ---------- Чат по заявке ----------

async def api_order_chat_list(request: web.Request):
    uid = request["uid"]
    order_id = int(request.match_info["order_id"])
    await _load_order_for_participant(order_id, uid)
    after_id = int(request.query.get("after_id", "0") or 0)
    rows = await get_order_chat_messages_after(order_id, after_id)
    return web.json_response(rows_to_list(rows))


async def api_order_chat_send(request: web.Request):
    uid = request["uid"]
    order_id = int(request.match_info["order_id"])
    body = await _json_body(request)
    text = str(body.get("text") or "").strip()[:4000]
    if not text:
        raise ApiError("Сообщение не может быть пустым.")
    peer = await get_order_chat_peer(order_id, uid)
    if not peer:
        raise ApiError("Чат по этой заявке сейчас закрыт.", status=403)
    sender_label = "👤 <b>Клиент</b>" if peer["side"] == "client" else "🧑‍💼 <b>Исполнитель</b>"
    bot = request.app["bot"]
    try:
        delivered = await bot.send_message(peer["peer_id"], f"{sender_label}\n\n{html_escape(text)}", parse_mode="HTML")
    except Exception as e:
        raise ApiError(f"Не удалось отправить сообщение собеседнику: {e}", status=502)
    await save_order_chat_message(order_id, uid, peer["peer_id"], delivered.message_id, "text", text)
    await log_order_event(order_id, uid, "chat_message", "Новое сообщение в анонимном чате (Mini App)")
    await create_notification(peer["peer_id"], "chat", f"💬 Новое сообщение по заявке #{order_id}", "Откройте чат, чтобы прочитать сообщение.", order_id)
    return web.json_response({"ok": True})


# ---------- Исполнитель ----------

async def api_executor_apply(request: web.Request):
    uid = request["uid"]
    body = await _json_body(request)
    experience = str(body.get("experience") or "")[:1000]
    services = str(body.get("services") or "")[:500]
    comment = str(body.get("comment") or "")[:1000]
    app_id = await create_executor_application(uid, experience, services, comment)
    if not app_id:
        raise ApiError("У вас уже есть активная заявка на роль исполнителя.")
    bot = request.app["bot"]
    for admin_id in await get_admin_ids():
        try:
            await bot.send_message(admin_id, f"🆕 Новая заявка на роль исполнителя #{app_id} (подана через Mini App). Откройте «Заявки на роль исполнителя» в админ-панели.")
        except Exception:
            pass
    return web.json_response({"ok": True, "application_id": app_id})


async def api_executor_apply_answer(request: web.Request):
    uid = request["uid"]
    app_id = int(request.match_info["app_id"])
    body = await _json_body(request)
    answer = str(body.get("answer") or "")[:1000]
    if not answer:
        raise ApiError("Ответ не может быть пустым.")
    app_row = await get_active_executor_application(uid)
    if not app_row or app_row["id"] != app_id or app_row["status"] != "question":
        raise ApiError("Нет ожидающего ответа вопроса по этой заявке.")
    await answer_executor_application(app_id, answer)
    bot = request.app["bot"]
    for admin_id in await get_admin_ids():
        try:
            await bot.send_message(admin_id, f"💬 Исполнитель ответил по заявке #{app_id} (Mini App). Заявка снова ожидает решения.")
        except Exception:
            pass
    return web.json_response({"ok": True})


async def api_executor_available_orders(request: web.Request):
    rows = await get_free_orders(30)
    return web.json_response(rows_to_list(rows))


async def api_executor_active_order(request: web.Request):
    row = await get_executor_active_order(request["uid"])
    return web.json_response(row_to_dict(row))


async def api_executor_history(request: web.Request):
    rows = await get_executor_history(request["uid"], limit=30)
    return web.json_response(rows_to_list(rows))


async def api_executor_stats(request: web.Request):
    stats = await get_executor_detailed_stats(request["uid"])
    return web.json_response(jsonable(stats))


async def api_executor_availability(request: web.Request):
    body = await _json_body(request)
    await set_executor_available(request["uid"], bool(body.get("available")))
    return web.json_response({"ok": True})


async def api_executor_notify(request: web.Request):
    body = await _json_body(request)
    await set_executor_notify_enabled(request["uid"], bool(body.get("enabled")))
    return web.json_response({"ok": True})


# ---------- Баланс, пополнение, вывод ----------

async def api_transactions(request: web.Request):
    rows = await get_user_transactions(request["uid"], limit=50)
    return web.json_response(rows_to_list(rows))


async def api_deposit_create(request: web.Request):
    uid = request["uid"]
    body = await _json_body(request)
    provider = body.get("provider")
    if provider not in ("cryptobot", "xrocket"):
        raise ApiError("Неизвестный способ пополнения.")
    try:
        amount = float(body.get("amount"))
    except (TypeError, ValueError):
        raise ApiError("Некорректная сумма.")
    if provider == "xrocket" and not xrocket.is_configured():
        raise ApiError("xRocket сейчас недоступен.")
    if provider == "cryptobot" and not cryptobot.is_configured():
        raise ApiError("CryptoBot сейчас недоступен.")
    min_deposit = await get_payment_min_amount(provider, "deposit")
    if amount < min_deposit:
        raise ApiError(f"Минимальная сумма пополнения — {min_deposit:.2f} USDT.")
    if not await is_payment_provider_enabled(provider, "deposit"):
        raise ApiError(f"{PAYMENT_PROVIDER_LABELS.get(provider, provider)} временно на техническом обслуживании.")
    try:
        if provider == "cryptobot":
            invoice = await cryptobot.create_invoice(amount, f"Пополнение TornadoPay (ID {uid})", str(uid))
            key = f"cryptobot:{invoice['invoice_id']}"
            link = invoice.get("mini_app_invoice_url") or invoice.get("bot_invoice_url")
            invoice_id = invoice.get("invoice_id")
        else:
            invoice = await xrocket.create_invoice(amount, f"Пополнение баланса TornadoPay (ID {uid})", str(uid))
            key = f"xrocket:{invoice['id']}"
            link = invoice["link"]
            invoice_id = invoice["id"]
        await create_deposit(uid, key, amount)
    except Exception as e:
        print(f"[webapp deposit {provider}] {e}")
        raise ApiError("Не удалось создать счёт. Попробуйте позже.", status=502)
    return web.json_response({"provider": provider, "invoice_id": invoice_id, "pay_url": link, "amount": amount})


async def api_deposit_check(request: web.Request):
    provider = request.match_info["provider"]
    invoice_id = request.match_info["invoice_id"]
    if provider not in ("cryptobot", "xrocket"):
        raise ApiError("Неизвестный способ пополнения.")
    key = f"{provider}:{invoice_id}"
    try:
        invoice = await (cryptobot.get_invoice(invoice_id) if provider == "cryptobot" else xrocket.get_invoice(invoice_id))
    except Exception as e:
        raise ApiError(f"Не удалось проверить оплату: {e}", status=502)
    status = invoice.get("status")
    paid = status in ("paid", "active_paid")
    if not paid:
        return web.json_response({"paid": False, "status": status})
    amount = invoice.get("paid_amount") or invoice.get("amount") or invoice.get("priceAmount")
    if provider == "xrocket":
        try:
            payments = await xrocket.get_invoice_payments(invoice_id)
        except Exception as e:
            print(f"[webapp xrocket payments] {e}")
            payments = []
        if payments:
            p = payments[-1]
            amount = p.get("receiveAmount") or p.get("payAmount") or amount
    result = await mark_deposit_paid(key, amount)
    if not result:
        return web.json_response({"paid": True, "already_credited": True})
    bot = request.app["bot"]
    referral_bonus = result.get("referral_bonus")
    if referral_bonus:
        try:
            await bot.send_message(
                referral_bonus["referrer_id"],
                f"🤝 <b>Реферальное вознаграждение</b>\n\nНачислено <b>{referral_bonus['amount']:.4f} USDT</b> за первое пополнение вашего реферала.",
                parse_mode="HTML",
            )
        except Exception:
            pass
    return web.json_response({"paid": True, "credited_amount": result["amount"]})


async def api_withdrawal_create(request: web.Request):
    uid = request["uid"]
    body = await _json_body(request)
    provider = body.get("provider")
    if provider not in ("cryptobot", "xrocket"):
        raise ApiError("Неизвестный способ вывода.")
    try:
        amount = float(body.get("amount"))
    except (TypeError, ValueError):
        raise ApiError("Некорректная сумма.")
    u = await get_user(uid)
    if not u or u["role"] != "executor" or u["executor_blocked"]:
        raise ApiError("Вывод доступен только для активных исполнителей.", status=403)
    if provider == "xrocket" and not xrocket.is_configured():
        raise ApiError("xRocket сейчас недоступен.")
    if provider == "cryptobot" and not cryptobot.is_configured():
        raise ApiError("CryptoBot сейчас недоступен.")
    min_withdraw = await get_payment_min_amount(provider, "withdraw")
    if amount < min_withdraw:
        raise ApiError(f"Минимальная сумма вывода — {min_withdraw:.2f} USDT.")
    if not await is_payment_provider_enabled(provider, "withdraw"):
        raise ApiError(f"{PAYMENT_PROVIDER_LABELS.get(provider, provider)} временно на техническом обслуживании.")
    if amount > float(u["balance"]) + 1e-9:
        raise ApiError(f"Недостаточно средств. Доступно: {float(u['balance']):.4f} USDT.")
    wid, result = await create_withdrawal_request(uid, amount)
    if result != "ok":
        raise ApiError("У вас уже есть заявка на вывод в обработке, либо недостаточно средств.")
    try:
        if provider == "cryptobot":
            check = await cryptobot.create_check(amount)
            link = check.get("bot_check_url") or check.get("mini_app_check_url")
            if not link:
                raise RuntimeError("CryptoBot не вернул ссылку на чек")
            provider_id = str(check.get("id") or check.get("hash") or "")
            await set_withdrawal_provider(wid, "cryptobot", provider_id, link, "active")
            await approve_withdrawal(wid, "CryptoBot check created (Mini App)")
            return web.json_response({"ok": True, "withdrawal_id": wid, "provider": "cryptobot", "pay_url": link})

        payout = await xrocket.create_payout(amount, uid, description=f"TornadoPay withdrawal #{wid}", client_payout_id=f"tp-wd-{wid}")
        provider_id = str(payout.get("payoutId") or payout.get("id") or "")
        provider_state = str(payout.get("status") or "finished")
        if not provider_id:
            raise RuntimeError("xRocket не вернул ID перевода")
        if provider_state != "finished":
            raise RuntimeError(f"xRocket создал перевод {provider_id}, но его статус: {provider_state}")
        await set_withdrawal_provider(wid, "xrocket", provider_id, None, provider_state)
        result2 = await approve_withdrawal(wid, "xRocket payout created (Mini App)")
        if not result2:
            raise RuntimeError(f"Заявка #{wid} уже обработана или не найдена")
        return web.json_response({"ok": True, "withdrawal_id": wid, "provider": "xrocket"})
    except Exception as e:
        print(f"[webapp withdraw {provider}] {e}")
        await mark_withdrawal_error(wid, f"{provider} error: {str(e)[:500]}")
        raise ApiError(f"Заявка #{wid} передана администратору, средства зарезервированы. Причина: {e}", status=502)


# ---------- Рефералка ----------

async def api_referrals(request: web.Request):
    uid = request["uid"]
    settings = await get_referral_settings()
    stats = await get_referral_stats(uid)
    bot_username = request.app.get("bot_username")
    link = f"https://t.me/{bot_username}?start=ref_{uid}" if bot_username else None
    return web.json_response({
        "link": link,
        "percent": settings["percent"],
        "flat_bonus": settings["flat_bonus"],
        "count": stats["count"],
        "total_earned": stats["total_earned"],
    })


# ---------- Уведомления ----------

async def api_notifications(request: web.Request):
    uid = request["uid"]
    rows = await get_notifications(uid, limit=50)
    unread = await get_unread_notifications_count(uid)
    return web.json_response({"items": rows_to_list(rows), "unread": unread})


async def api_notifications_read(request: web.Request):
    await mark_notifications_read(request["uid"])
    return web.json_response({"ok": True})


def setup_webapp_routes(app: web.Application, bot_token: str, static_dir: str):
    """Регистрирует API мини-приложения и раздачу статики на уже
    существующем aiohttp Application (том же, что слушает вебхук xRocket)."""
    app["bot_token"] = bot_token
    app.middlewares.append(api_middleware)

    app.router.add_get("/api/me", api_me)
    app.router.add_post("/api/agreement/accept", api_agreement_accept)

    app.router.add_get("/api/services", api_services)

    app.router.add_post("/api/orders", api_orders_create)
    app.router.add_get("/api/orders", api_orders_list)
    app.router.add_get("/api/orders/{order_id}", api_order_detail)
    app.router.add_get("/api/orders/{order_id}/qr-image", api_order_qr_image)
    app.router.add_post("/api/orders/{order_id}/claim", api_order_claim)
    app.router.add_post("/api/orders/{order_id}/complete", api_order_complete)
    app.router.add_post("/api/orders/{order_id}/confirm", api_order_confirm)
    app.router.add_post("/api/orders/{order_id}/dispute", api_order_dispute)
    app.router.add_post("/api/orders/{order_id}/rate", api_order_rate)
    app.router.add_get("/api/orders/{order_id}/chat", api_order_chat_list)
    app.router.add_post("/api/orders/{order_id}/chat", api_order_chat_send)

    app.router.add_post("/api/executor/apply", api_executor_apply)
    app.router.add_post("/api/executor/apply/{app_id}/answer", api_executor_apply_answer)
    app.router.add_get("/api/executor/available-orders", api_executor_available_orders)
    app.router.add_get("/api/executor/active-order", api_executor_active_order)
    app.router.add_get("/api/executor/history", api_executor_history)
    app.router.add_get("/api/executor/stats", api_executor_stats)
    app.router.add_post("/api/executor/availability", api_executor_availability)
    app.router.add_post("/api/executor/notify", api_executor_notify)

    app.router.add_get("/api/transactions", api_transactions)
    app.router.add_post("/api/deposits", api_deposit_create)
    app.router.add_get("/api/deposits/{provider}/{invoice_id}/status", api_deposit_check)
    app.router.add_post("/api/withdrawals", api_withdrawal_create)

    app.router.add_get("/api/referrals", api_referrals)

    app.router.add_get("/api/notifications", api_notifications)
    app.router.add_post("/api/notifications/read", api_notifications_read)

    async def index(request):
        return web.FileResponse(os.path.join(static_dir, "index.html"))

    app.router.add_get("/webapp", index)
    app.router.add_get("/webapp/", index)
    app.router.add_static("/webapp/", path=static_dir, name="webapp_static")
