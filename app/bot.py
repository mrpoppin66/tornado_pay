import os
from html import escape
from typing import Any, Awaitable, Callable, Dict
from aiogram import BaseMiddleware, Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile, TelegramObject
from dotenv import load_dotenv
from .db import (
    init_db, close_db, ensure_user, get_user, get_services, get_service, create_order, calculate_order_commission,
    get_orders, ORDER_STATUS_LABELS, get_exchange_rate, start_exchange_rate_updater,
    get_active_executor_application, get_latest_executor_application,
    create_executor_application, answer_executor_application,
    EXECUTOR_APPLICATION_STATUSES, get_free_orders, claim_order, complete_executor_order,
    confirm_order_by_client, dispute_order_by_client,
    get_order_chat_peer, save_order_chat_message, get_executor_active_order, get_executor_history,
    create_withdrawal_request, get_user_transactions, get_chat_unread_count, get_chat_unread_for_orders,
    mark_chat_read, get_recent_chat_messages, get_executor_detailed_stats,
    add_order_evidence, log_order_event, create_notification, get_notifications, get_unread_notifications_count, mark_notifications_read,
    get_order_events, get_order_evidence, set_user_blocked, get_executor_profile, get_executor_history_detailed, get_user_blocked,
    get_user_agreement_accepted, accept_user_agreement,
)
from .admin import admin_router, ADMIN_IDS

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")

dp = Dispatcher()
dp.include_router(admin_router)

START_BANNER_PATH = os.path.join(os.path.dirname(__file__), "assets", "start_banner.png")
SUPPORT_BANNER_PATH = os.path.join(os.path.dirname(__file__), "assets", "support_banner.png")
AGREEMENT_URL = "https://telegra.ph/Polzovatelskoe-soglashenie-servisa-TornadoPay-09-09"


def agreement_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📄 Читать соглашение", url=AGREEMENT_URL)],
        [InlineKeyboardButton(text="✅ Я принимаю условия", callback_data="agree_tos")],
    ])


class AgreementMiddleware(BaseMiddleware):
    """Блокирует любые действия в боте, пока пользователь не принял
    пользовательское соглашение. Пропускает только /start (там пользователь
    и видит предложение принять условия) и саму кнопку принятия."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        if user is None:
            return await handler(event, data)

        if isinstance(event, Message):
            if event.text and event.text.split()[0].split("@")[0] == "/start":
                return await handler(event, data)
        elif isinstance(event, CallbackQuery):
            if event.data == "agree_tos":
                return await handler(event, data)

        accepted = await get_user_agreement_accepted(user.id)
        if accepted:
            return await handler(event, data)

        warning = (
            "⚠️ Чтобы пользоваться TornadoPay, необходимо принять "
            "пользовательское соглашение сервиса."
        )
        if isinstance(event, CallbackQuery):
            await event.answer("Сначала примите условия соглашения.", show_alert=True)
            try:
                await event.message.answer(warning, reply_markup=agreement_kb(), parse_mode="HTML")
            except Exception:
                pass
        elif isinstance(event, Message):
            await event.answer(warning, reply_markup=agreement_kb(), parse_mode="HTML")
        return None


dp.message.outer_middleware(AgreementMiddleware())
dp.callback_query.outer_middleware(AgreementMiddleware())

class UserStates(StatesGroup):
    waiting_order_amount = State()
    executor_experience = State()
    executor_services = State()
    executor_comment = State()
    executor_answer = State()
    chat_message = State()
    withdrawal_amount = State()

# Custom_emoji_id премиум-эмодзи для кнопок главного меню. Работает только
# если владелец бота (аккаунт, на который выпущен BOT_TOKEN) имеет активную
# подписку Telegram Premium — иначе Telegram просто покажет обычный текст
# кнопки без иконки, ошибки не будет.
#
# Чтобы получить id нужного эмодзи: администратор пишет боту команду
# /emoji_id, затем отправляет сообщение с этим эмодзи (вставленным именно
# из вкладки Premium в панели эмодзи Telegram) — бот пришлёт его
# custom_emoji_id. Впишите полученные значения ниже вместо None.
MENU_EMOJI_IDS = {
    "services": None,
    "profile": None,
    "executor": None,
    "support": None,
    "notifications": None,
    "admin": None,
}

def menu(user_id=None, role=None):
    executor_button = (
        InlineKeyboardButton(
            text="🧑‍💼 ЛК Исполнителя", callback_data="executor",
            icon_custom_emoji_id=MENU_EMOJI_IDS["executor"])
        if role == "executor" else
        InlineKeyboardButton(
            text="🧑‍💼 Стать исполнителем", callback_data="executor",
            icon_custom_emoji_id=MENU_EMOJI_IDS["executor"])
    )
    kb = [
        [InlineKeyboardButton(text="🛒 Услуги", callback_data="services",
                               icon_custom_emoji_id=MENU_EMOJI_IDS["services"]),
         InlineKeyboardButton(text="👤 Профиль", callback_data="profile",
                               icon_custom_emoji_id=MENU_EMOJI_IDS["profile"])],
        [executor_button,
         InlineKeyboardButton(text="🆘 Поддержка", callback_data="support",
                               icon_custom_emoji_id=MENU_EMOJI_IDS["support"])],
    ]
    kb.append([InlineKeyboardButton(text="🔔 Уведомления", callback_data="notifications",
                                     icon_custom_emoji_id=MENU_EMOJI_IDS["notifications"])])
    if user_id in ADMIN_IDS:
        kb.append([InlineKeyboardButton(text="🛠 Админ-панель", callback_data="adm:menu",
                                         icon_custom_emoji_id=MENU_EMOJI_IDS["admin"])])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def back():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="back")]
    ])

async def safe_edit(c: CallbackQuery, text, reply_markup=None, parse_mode="HTML"):
    """Заменяет текущий экран новым текстом. Первое меню после /start —
    это фото с подписью, а фото-сообщение нельзя отредактировать как
    текстовое (Telegram это не поддерживает). В этом случае старое
    сообщение удаляется и текст отправляется новым сообщением."""
    if c.message.photo:
        try:
            await c.message.delete()
        except Exception:
            pass
        await c.message.answer(text, reply_markup=reply_markup, parse_mode=parse_mode)
    else:
        await c.message.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)

def chat_kb(order_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Закрыть чат", callback_data=f"chat:close:{order_id}")]
    ])

# Этот обработчик зарегистрирован ДО /start специально: пока пользователь
# находится в чате, даже сообщения вида /start считаются сообщениями чата.
@dp.message(UserStates.chat_message)
async def order_chat_message(m: Message, state: FSMContext):
    data = await state.get_data()
    order_id = data.get("order_id")
    if not order_id:
        await state.clear()
        await m.answer("Чат закрыт.", reply_markup=back())
        return

    peer = await get_order_chat_peer(order_id, m.from_user.id)
    if not peer:
        await state.clear()
        await m.answer(
            f"🔒 <b>Чат по заявке #{order_id} закрыт.</b>\n\n"
            "Заявка больше не находится в активном статусе или вы больше не являетесь её участником.",
            reply_markup=back(), parse_mode="HTML")
        return

    # Никнеймы, Telegram ID и любые другие контактные данные собеседнику
    # никогда не передаются. Сообщение доставляется копированием через бота.
    sender_label = "👤 <b>Клиент</b>" if peer["side"] == "client" else "🧑‍💼 <b>Исполнитель</b>"
    try:
        if m.text is not None:
            delivered = await m.bot.send_message(
                peer["peer_id"],
                f"{sender_label}\n\n{escape(m.text)}",
                parse_mode="HTML",
                reply_markup=None,
            )
            content_type = "text"
            text_content = m.text[:4000]
        else:
            await m.bot.send_message(peer["peer_id"], sender_label, parse_mode="HTML")
            delivered = await m.bot.copy_message(
                chat_id=peer["peer_id"],
                from_chat_id=m.chat.id,
                message_id=m.message_id,
            )
            content_type = str(m.content_type)
            text_content = (m.caption or "")[:4000]

        await save_order_chat_message(
            order_id, m.from_user.id, peer["peer_id"], delivered.message_id,
            content_type, text_content
        )
        if content_type != "text":
            await add_order_evidence(order_id, m.from_user.id, m.message_id, content_type, m.caption or "")
        await log_order_event(order_id, m.from_user.id, "chat_message", "Новое сообщение в анонимном чате")
        await create_notification(peer["peer_id"], "chat", f"💬 Новое сообщение по заявке #{order_id}", "Откройте чат, чтобы прочитать сообщение.", order_id)
        await m.answer("✓ Сообщение отправлено", reply_markup=chat_kb(order_id))
    except Exception as e:
        print(f"[Order chat] order={order_id}: {e}")
        await m.answer("❌ Не удалось отправить сообщение. Попробуйте ещё раз.", reply_markup=chat_kb(order_id))

@dp.message(CommandStart())
async def start(m: Message):
    await ensure_user(m.from_user.id, m.from_user.username)

    if not await get_user_agreement_accepted(m.from_user.id):
        await m.answer(
            "👋 Добро пожаловать в <b>TornadoPay</b>!\n\n"
            "Прежде чем начать работу, пожалуйста, ознакомьтесь с "
            "пользовательским соглашением сервиса и примите его условия — "
            "это обязательное условие для использования Бота.",
            reply_markup=agreement_kb(), parse_mode="HTML")
        return

    user = await get_user(m.from_user.id)
    rate = get_exchange_rate()
    caption = (
        f"👋 Добро пожаловать в <b>TornadoPay</b>!\n\n"
        f"Маркетплейс услуг с оплатой в криптовалюте.\n"
        f"Выберите услугу и укажите сумму в рублях.\n\n"
        f"📊 Текущий курс: 1 USDT = {rate:.2f} RUB"
    )
    kb = menu(m.from_user.id, user[3] if user else None)
    try:
        await m.answer_photo(FSInputFile(START_BANNER_PATH), caption=caption, reply_markup=kb, parse_mode="HTML")
    except Exception as e:
        print(f"[start banner] {e}")
        await m.answer(caption, reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data == "agree_tos")
async def agree_tos(c: CallbackQuery):
    await accept_user_agreement(c.from_user.id)
    user = await get_user(c.from_user.id)
    rate = get_exchange_rate()
    caption = (
        f"✅ Спасибо! Условия пользовательского соглашения приняты.\n\n"
        f"👋 Добро пожаловать в <b>TornadoPay</b>!\n\n"
        f"Маркетплейс услуг с оплатой в криптовалюте.\n"
        f"Выберите услугу и укажите сумму в рублях.\n\n"
        f"📊 Текущий курс: 1 USDT = {rate:.2f} RUB"
    )
    kb = menu(c.from_user.id, user[3] if user else None)
    try:
        await c.message.delete()
    except Exception:
        pass
    try:
        await c.message.answer_photo(FSInputFile(START_BANNER_PATH), caption=caption, reply_markup=kb, parse_mode="HTML")
    except Exception as e:
        print(f"[start banner] {e}")
        await c.message.answer(caption, reply_markup=kb, parse_mode="HTML")
    await c.answer()

@dp.callback_query(F.data == "balance")
async def balance(c: CallbackQuery):
    u = await get_user(c.from_user.id)
    await safe_edit(c,
        f"💰 <b>Баланс</b>\n\n{u[2]:.2f} USDT\n\n"
        "CryptoBot/xRocket подключим следующим этапом.",
        reply_markup=back(), parse_mode="HTML")
    await c.answer()

@dp.callback_query(F.data == "profile")
async def profile(c: CallbackQuery):
    u = await get_user(c.from_user.id)
    if not u:
        await c.answer("Профиль не найден.", show_alert=True)
        return
    kb_rows = [
        [InlineKeyboardButton(text="📋 Мои заявки", callback_data="orders")],
        [InlineKeyboardButton(text="💰 Баланс", callback_data="balance")],
        [InlineKeyboardButton(text="📊 История операций", callback_data="profile:transactions")],
        [InlineKeyboardButton(text="💳 Пополнить", callback_data="profile:deposit")],
    ]
    if u[3] == "executor":
        kb_rows.append([InlineKeyboardButton(text="💸 Вывести", callback_data="exec:withdraw")])
    kb_rows.append([InlineKeyboardButton(text="⬅️ Главное меню", callback_data="back")])
    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
    role_label = "Исполнитель" if u[3] == "executor" else "Пользователь"
    await safe_edit(c,
        f"👤 <b>Личный кабинет</b>\n\n"
        f"ID: <code>{u[0]}</code>\n"
        f"Роль: <b>{role_label}</b>\n"
        f"Баланс: <b>{float(u[2]):.4f} USDT</b>",
        reply_markup=kb, parse_mode="HTML")
    await c.answer()

@dp.callback_query(F.data == "profile:transactions")
async def profile_transactions(c: CallbackQuery):
    rows = await get_user_transactions(c.from_user.id)
    text = "📊 <b>История операций</b>\n\n"
    if not rows:
        text += "Операций пока нет."
    else:
        for x in rows:
            sign = "+" if float(x[1]) > 0 else ""
            text += f"<b>{sign}{float(x[1]):.4f} USDT</b> — {escape(x[3])}\n{x[4]:%d.%m.%Y %H:%M}\n\n"
    await safe_edit(c, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Личный кабинет", callback_data="profile")]
    ]), parse_mode="HTML")
    await c.answer()

@dp.callback_query(F.data == "profile:deposit")
async def profile_deposit(c: CallbackQuery):
    await c.answer("Пополнение будет подключено на этапе интеграции CryptoBot/xRocket.", show_alert=True)

@dp.callback_query(F.data == "services")
async def services(c: CallbackQuery):
    rows = await get_services()
    rate = get_exchange_rate()
    min_rub_text = []
    for x in rows:
        min_rub = float(x[3]) * rate
        min_rub_text.append(f"{x[1]} (мин. {x[3]:.2f} USDT / ~{min_rub:.0f} RUB)")

    kb = [[InlineKeyboardButton(text=text, callback_data=f"svc:{rows[i][0]}")] for i, text in enumerate(min_rub_text)]
    kb.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back")])
    await safe_edit(c,
        "🛒 <b>Услуги</b>\n\nВыберите услугу:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await c.answer()

@dp.callback_query(F.data.startswith("svc:"))
async def service_select(c: CallbackQuery, state: FSMContext):
    sid = int(c.data.split(":")[1])
    service = await get_service(sid)
    if not service:
        await c.answer("Услуга не найдена", show_alert=True)
        return

    rate = get_exchange_rate()
    await state.update_data(service_id=sid, service_name=service[1],
                           min_amount_usdt=float(service[3]),
                           owner_comm=float(service[4]),
                           executor_comm=float(service[5]))
    await state.set_state(UserStates.waiting_order_amount)

    min_rub = float(service[3]) * rate

    await c.message.edit_text(
        f"🛒 <b>{service[1]}</b>\n\n"
        f"{service[2]}\n\n"
        f"Минимальная сумма: {service[3]:.2f} USDT (~{min_rub:.0f} RUB)\n"
        f"Текущий курс: 1 USDT = {rate:.2f} RUB\n\n"
        f"Пришлите сумму в <b>рублях</b> (например 300 или 150.50):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ К услугам", callback_data="services")]
        ]), parse_mode="HTML")
    await c.answer()

@dp.message(UserStates.waiting_order_amount)
async def order_amount(m: Message, state: FSMContext):
    if await get_user_blocked(m.from_user.id):
        await m.answer("🚫 Ваш аккаунт заблокирован администрацией.", reply_markup=back())
        await state.clear()
        return
    if not m.text:
        await m.answer("Пришлите сумму числом.")
        return

    try:
        amount_rub = float(m.text.strip().replace(",", "."))
    except ValueError:
        await m.answer("Неверный формат. Пришлите сумму числом (например 300 или 150.50).")
        return

    data = await state.get_data()
    # Курс фиксируется в момент создания заявки: один и тот же
    # используется для проверки минимума, записи в БД и показа клиенту
    rate = get_exchange_rate()
    min_amount_usdt = float(data["min_amount_usdt"])
    min_rub = min_amount_usdt * rate

    if amount_rub < min_rub:
        await m.answer(f"❌ Минимальная сумма: {min_rub:.2f} RUB ({min_amount_usdt:.2f} USDT)")
        return

    # Создаём заявку (курс передаём явно)
    oid, create_error = await create_order(m.from_user.id, data["service_id"], amount_rub, rate)
    if not oid:
        await state.clear()
        if create_error == "insufficient_balance":
            await m.answer("❌ Недостаточно USDT на балансе для создания заявки. Пополните баланс и попробуйте снова.", reply_markup=back())
        elif create_error == "below_minimum":
            await m.answer("❌ Сумма ниже минимальной для этой услуги.", reply_markup=back())
        elif create_error == "above_maximum":
            await m.answer("❌ Сумма выше максимальной для этой услуги.", reply_markup=back())
        else:
            await m.answer("❌ Не удалось создать заявку. Попробуйте ещё раз.", reply_markup=back())
        return

    # Финансовые значения считаются внутренне, но размеры комиссий
    # никогда не показываются клиенту или исполнителю.
    owner_comm = float(data["owner_comm"])
    executor_comm = float(data["executor_comm"])
    user_amount_usdt = amount_rub / rate
    commission_usdt, _owner_commission_amount, _executor_commission_amount = calculate_order_commission(
        user_amount_usdt, rate, owner_comm, executor_comm
    )
    total_amount_usdt = user_amount_usdt + commission_usdt

    await state.clear()
    await log_order_event(oid, m.from_user.id, "created", f"Заявка создана: {data['service_name']}")
    await create_notification(m.from_user.id, "order", f"📋 Заявка #{oid} создана", "Заявка ожидает исполнителя.", oid)
    await m.answer(
        f"🧾 <b>Заявка #{oid}</b>\n\n"
        f"Услуга: {data['service_name']}\n\n"
        f"<b>К оплате: {total_amount_usdt:.4f} USDT</b>\n"
        f"Вы получите: <b>{amount_rub:.2f} RUB</b>\n\n"
        f"Курс {rate:.2f} RUB/USDT зафиксирован. Ожидание исполнителя...",
        reply_markup=back(), parse_mode="HTML")

@dp.callback_query(F.data.startswith("order:view:"))
async def order_view(c: CallbackQuery):
    oid=int(c.data.split(":")[2])
    o=await get_order(oid)
    if not o or o[1] != c.from_user.id:
        await c.answer("Заявка недоступна.", show_alert=True); return
    await c.message.edit_text(f"📋 <b>Заявка #{oid}</b>\n\nСтатус: <b>{ORDER_STATUS_LABELS.get(o[9],o[9])}</b>\nСумма: <b>{float(o[4]):.2f} RUB</b>\nК оплате: <b>{float(o[7]):.4f} USDT</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💬 Чат",callback_data=f"chat:open:{oid}")],[InlineKeyboardButton(text="⬅️ Мои заявки",callback_data="orders")]]), parse_mode="HTML")
    await c.answer()

@dp.callback_query(F.data == "orders")
async def orders(c: CallbackQuery):
    rows = await get_orders(c.from_user.id)
    text = "📋 <b>Мои заявки</b>\n\n"
    kb = []
    if not rows:
        text += "Заявок пока нет."
    else:
        unread = await get_chat_unread_for_orders([x[0] for x in rows], c.from_user.id)
        for x in rows:
            text += (f"<b>#{x[0]} — {escape(x[1])}</b>\n"
                     f"Вы получите: {float(x[2]):.2f} RUB\n"
                     f"К оплате: <b>{float(x[4]):.4f} USDT</b>\n"
                     f"Статус: {ORDER_STATUS_LABELS.get(x[5], x[5])}\n\n")
            if x[6] and x[5] in ("in_progress", "awaiting_confirmation", "disputed"):
                count = unread.get(int(x[0]), 0)
                badge = f" 🔴 {count}" if count else ""
                kb.append([InlineKeyboardButton(text=f"💬 Чат по заявке #{x[0]}{badge}", callback_data=f"chat:open:{x[0]}")])
            if x[5] == "awaiting_confirmation":
                kb.append([InlineKeyboardButton(text=f"✅ Подтвердить #{x[0]}", callback_data=f"order:confirm:{x[0]}"),
                           InlineKeyboardButton(text="⚠️ Проблема", callback_data=f"order:dispute:{x[0]}")])
    kb.append([InlineKeyboardButton(text="⬅️ Главное меню", callback_data="back")])
    await c.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
    await c.answer()

@dp.callback_query(F.data.startswith("chat:open:"))
async def order_chat_open(c: CallbackQuery, state: FSMContext):
    order_id = int(c.data.split(":")[2])
    peer = await get_order_chat_peer(order_id, c.from_user.id)
    if not peer:
        await c.answer("Чат недоступен.", show_alert=True)
        return
    await mark_chat_read(order_id, c.from_user.id)
    await state.clear()
    await state.update_data(order_id=order_id)
    await state.set_state(UserStates.chat_message)
    role_text = "исполнителем" if peer["side"] == "client" else "клиентом"
    recent = await get_recent_chat_messages(order_id, 10)
    history_lines=[]
    for r in reversed(recent):
        who = "Вы" if r[1] == c.from_user.id else ("👤 Клиент" if peer["side"] == "executor" else "🧑‍💼 Исполнитель")
        if r[2] == "text" and r[3]:
            history_lines.append(f"{who}: {escape(r[3][:500])}")
    history = ""
    if history_lines:
        history = "\n\n<b>Последние сообщения:</b>\n" + "\n".join(history_lines)
    await c.message.edit_text(
        f"💬 <b>Чат по заявке #{order_id}</b>\n\n"
        f"Вы общаетесь {role_text} <b>строго через TornadoPay</b>.\n"
        "Username, имя профиля и ID собеседнику не передаются." + history + "\n\nОтправляйте сообщение следующим сообщением.",
        reply_markup=chat_kb(order_id), parse_mode="HTML")
    await c.answer()

@dp.callback_query(F.data.startswith("chat:close:"))
async def order_chat_close(c: CallbackQuery, state: FSMContext):
    order_id = int(c.data.split(":")[2])
    await state.clear()
    u = await get_user(c.from_user.id)
    if u and u[3] == "executor":
        await c.message.edit_text("🧑‍💼 <b>Кабинет исполнителя</b>\n\nВы вышли из чата.", reply_markup=executor_cabinet_kb(bool(u[7]), bool(await get_executor_active_order(c.from_user.id))), parse_mode="HTML")
    else:
        await c.message.edit_text("📋 <b>Мои заявки</b>\n\nВы вышли из чата.", reply_markup=back(), parse_mode="HTML")
    await c.answer("Чат закрыт")

def executor_application_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Подать заявку", callback_data="exec:apply")],
        [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="back")],
    ])


def executor_cabinet_kb(available=False, has_active=False):
    rows = [[InlineKeyboardButton(text=("🔴 Стать недоступным" if available else "🟢 Стать доступным"),
                                  callback_data=("exec:availability:0" if available else "exec:availability:1"))]]
    rows.append([InlineKeyboardButton(text="🆕 Заявки, которые можно взять", callback_data="exec:free")])
    if has_active:
        rows.append([InlineKeyboardButton(text="🔧 Активная заявка", callback_data="exec:active")])
    rows.append([InlineKeyboardButton(text="📋 История заявок", callback_data="exec:history")])
    rows.append([InlineKeyboardButton(text="💰 Баланс", callback_data="exec:balance")])
    rows.append([InlineKeyboardButton(text="💸 Вывести", callback_data="exec:withdraw")])
    rows.append([InlineKeyboardButton(text="⬅️ Главное меню", callback_data="back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

@dp.callback_query(F.data == "executor")
async def executor(c: CallbackQuery, state: FSMContext):
    await state.clear()
    u=await get_user(c.from_user.id)
    app=await get_latest_executor_application(c.from_user.id)
    if u and u[3]=="executor":
        if u[8]:
            await safe_edit(c, "🚫 <b>Доступ исполнителя заблокирован администрацией.</b>\n\nОбратитесь в поддержку.",reply_markup=back())
        else:
            stats=await get_executor_detailed_stats(c.from_user.id)
            active=await get_executor_active_order(c.from_user.id)
            status="🟢 Доступен" if u[7] else "🔴 Не доступен"
            await safe_edit(c,
                f"🧑‍💼 <b>ЛК Исполнителя</b>\n\n"
                f"Статус: {status}\n"
                f"💰 Баланс: <b>{float(u[2]):.4f} USDT</b>\n\n"
                f"📊 Выполнено: <b>{stats['completed']}</b>\n"
                f"❌ Отменено: <b>{stats['cancelled']}</b>\n"
                f"⚖️ Споров: <b>{stats['disputes']}</b>\n"
                f"⭐ Рейтинг: <b>{stats['rating']:.2f}</b> ({stats['ratings']})",
                reply_markup=executor_cabinet_kb(bool(u[7]),bool(active)))
    elif app and app[5] in ("pending","question"):
        label=EXECUTOR_APPLICATION_STATUSES[app[5]]
        text=f"🧑‍💼 <b>Заявка исполнителя</b>\n\nСтатус: <b>{label}</b>"
        if app[5]=="question":
            text += "\n\n💬 Администрация ожидает вашего ответа."
            kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💬 Ответить",callback_data=f"exec:answer:{app[0]}")],[InlineKeyboardButton(text="⬅️ Главное меню",callback_data="back")]])
        else:
            text += "\n\nМы уведомим вас после принятия решения."
            kb=back()
        await safe_edit(c, text,reply_markup=kb)
    elif app and app[5]=="rejected":
        reason=app[8] or "не указана"
        await safe_edit(c, f"❌ <b>Ваша заявка отклонена.</b>\n\nПричина: {escape(reason)}",reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📝 Подать новую заявку",callback_data="exec:apply")],[InlineKeyboardButton(text="⬅️ Главное меню",callback_data="back")]]))
    else:
        await safe_edit(c, "🧑‍💼 <b>Стать исполнителем</b>\n\nДля получения доступа к заявкам необходимо подать заявку.\n\nПосле заполнения она будет рассмотрена администрацией Tornado Pay.",reply_markup=executor_application_kb())
    await c.answer()

@dp.callback_query(F.data == "exec:apply")
async def executor_apply_start(c: CallbackQuery, state: FSMContext):
    app = await get_active_executor_application(c.from_user.id)
    if app:
        await c.answer("У вас уже есть активная заявка.", show_alert=True)
        return
    await state.set_state(UserStates.executor_experience)
    await c.message.edit_text(
        "📝 <b>Заявка исполнителя — шаг 1/3</b>\n\n"
        "Кратко расскажите о себе и вашем опыте.\n\n"
        "Эта информация доступна только администрации.", reply_markup=back(), parse_mode="HTML")
    await c.answer()


@dp.message(UserStates.executor_experience)
async def executor_experience(m: Message, state: FSMContext):
    if not m.text or not m.text.strip():
        await m.answer("Пожалуйста, напишите краткую информацию об опыте.")
        return
    await state.update_data(experience=m.text.strip())
    await state.set_state(UserStates.executor_services)
    await m.answer("📝 <b>Шаг 2/3</b>\n\nКакие услуги вы готовы выполнять?\n\nЭта информация доступна только администрации.", parse_mode="HTML")


@dp.message(UserStates.executor_services)
async def executor_services(m: Message, state: FSMContext):
    if not m.text or not m.text.strip():
        await m.answer("Пожалуйста, перечислите услуги.")
        return
    await state.update_data(services=m.text.strip())
    await state.set_state(UserStates.executor_comment)
    await m.answer("📝 <b>Шаг 3/3</b>\n\nДополнительный комментарий для администрации (можно отправить «-»).", parse_mode="HTML")


@dp.message(UserStates.executor_comment)
async def executor_comment(m: Message, state: FSMContext):
    comment = (m.text or "").strip()
    if not comment:
        await m.answer("Введите комментарий или отправьте «-».")
        return
    data = await state.get_data()
    comment = "" if comment == "-" else comment
    app_id = await create_executor_application(m.from_user.id, data["experience"], data["services"], comment)
    await state.clear()
    if not app_id:
        await m.answer("⏳ У вас уже есть активная заявка на рассмотрении.")
        return
    await m.answer("📋 <b>Ваша заявка отправлена на рассмотрение.</b>\n\n⏳ Статус: <b>На рассмотрении</b>\n\nМы уведомим вас после принятия решения.", reply_markup=back(), parse_mode="HTML")

    # Уведомляем всех администраторов. Внутренние поля отправляются только им.
    from .admin import notify_new_executor_application
    await notify_new_executor_application(app_id, m.bot)


@dp.callback_query(F.data.startswith("exec:answer:"))
async def executor_answer_start(c: CallbackQuery, state: FSMContext):
    app_id = int(c.data.split(":")[2])
    app = await get_active_executor_application(c.from_user.id)
    if not app or app[0] != app_id or app[5] != "question":
        await c.answer("Эта заявка больше не ожидает ответа.", show_alert=True)
        return
    await state.update_data(application_id=app_id)
    await state.set_state(UserStates.executor_answer)
    await c.message.edit_text("💬 <b>Ответ администрации</b>\n\nНапишите ответ на вопрос администрации. Его увидит только администрация.", reply_markup=back(), parse_mode="HTML")
    await c.answer()


@dp.message(UserStates.executor_answer)
async def executor_answer(m: Message, state: FSMContext):
    if not m.text or not m.text.strip():
        await m.answer("Введите ответ текстом.")
        return
    data = await state.get_data()
    await answer_executor_application(data["application_id"], m.text.strip())
    await state.clear()
    await m.answer("✅ Ответ отправлен администрации.\n\n⏳ Статус: <b>На рассмотрении</b>", reply_markup=back(), parse_mode="HTML")
    from .admin import notify_executor_application_answer
    await notify_executor_application_answer(data["application_id"], m.bot)


@dp.callback_query(F.data == "exec:free")
async def executor_free_orders(c: CallbackQuery):
    u = await get_user(c.from_user.id)
    if not u or u[3] != "executor" or u[8]:
        await c.answer("Доступ запрещён.", show_alert=True); return
    if not u[7]:
        await c.answer("Сначала включите доступность в ЛК Исполнителя.", show_alert=True); return
    if await get_executor_active_order(c.from_user.id):
        await c.answer("Сначала завершите активную заявку.", show_alert=True); return
    rows = await get_free_orders()
    text = "🆕 <b>Свободные заявки</b>\n\n"
    kb=[]
    if not rows:
        text += "Свободных заявок сейчас нет."
    else:
        for r in rows:
            text += (f"#{r[0]} — {escape(r[1])}\n"
                     f"Переводите: <b>{float(r[2]):.2f} RUB</b> → получите: <b>{(float(r[3])+float(r[4])):.4f} USDT</b>\n\n")
            kb.append([InlineKeyboardButton(text=f"Открыть #{r[0]}", callback_data=f"exec:order:{r[0]}")])
    kb.append([InlineKeyboardButton(text="⬅️ ЛК Исполнителя", callback_data="executor")])
    await c.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
    await c.answer()

@dp.callback_query(F.data.startswith("exec:order:"))
async def executor_order_detail(c: CallbackQuery):
    oid=int(c.data.split(":")[2])
    rows=await get_free_orders(50)
    r=next((x for x in rows if int(x[0])==oid),None)
    if not r:
        await c.answer("Заявка уже недоступна.",show_alert=True); return
    text=(f"🆕 <b>Заявка #{r[0]}</b>\n\n"
          f"Услуга: <b>{escape(r[1])}</b>\n\n"
          f"Вы переводите: <b>{float(r[2]):.2f} RUB</b>\n"
          f"Получите на баланс: <b>{(float(r[3])+float(r[4])):.4f} USDT</b>")
    kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Взять заявку",callback_data=f"exec:claim:{oid}")],[InlineKeyboardButton(text="⬅️ Свободные заявки",callback_data="exec:free")]])
    await c.message.edit_text(text,reply_markup=kb,parse_mode="HTML"); await c.answer()

@dp.callback_query(F.data.startswith("exec:claim:"))
async def executor_claim(c: CallbackQuery):
    oid=int(c.data.split(":")[2])
    client_id,result=await claim_order(oid,c.from_user.id)
    if result != "ok":
        msgs={'unavailable':'Вы недоступны для новых заявок.','active_exists':'У вас уже есть активная заявка.','already_taken':'Заявка уже взята другим исполнителем.','own_order':'Нельзя взять собственную заявку.','not_found':'Заявка не найдена.'}
        await c.answer(msgs.get(result,'Не удалось взять заявку.'),show_alert=True); return
    await c.answer("Заявка взята.",show_alert=True)
    await log_order_event(oid, c.from_user.id, "claimed", "Исполнитель взял заявку")
    await create_notification(client_id, "order", f"👷 Исполнитель найден по заявке #{oid}", "Заявка принята исполнителем.", oid)
    try:
        await c.bot.send_message(client_id, f"👷 <b>Исполнитель найден</b>\n\nВаша заявка #{oid} принята исполнителем.\nТеперь вы можете общаться через анонимный чат TornadoPay.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💬 Открыть чат",callback_data=f"chat:open:{oid}")]]), parse_mode="HTML")
    except Exception as e: print(f"[Notify claim] {e}")
    await executor_active(c)

@dp.callback_query(F.data.startswith("exec:done:"))
async def executor_done(c: CallbackQuery):
    oid=int(c.data.split(":")[2])
    client_id=await complete_executor_order(oid,c.from_user.id)
    if not client_id:
        await c.answer("Нельзя отметить эту заявку выполненной.",show_alert=True); return
    await log_order_event(oid, c.from_user.id, "completed", "Исполнитель отметил заявку выполненной")
    await create_notification(client_id, "order", f"⏳ Заявка #{oid} отмечена выполненной", "Проверьте результат.", oid)
    try:
        await c.bot.send_message(client_id, f"⏳ <b>Заявка #{oid} отмечена выполненной.</b>\n\nПроверьте результат и подтвердите выполнение либо откройте спор.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💬 Чат",callback_data=f"chat:open:{oid}")],[InlineKeyboardButton(text="✅ Подтвердить",callback_data=f"order:confirm:{oid}"),InlineKeyboardButton(text="⚠️ Проблема",callback_data=f"order:dispute:{oid}")]]), parse_mode="HTML")
    except Exception as e: print(f"[Notify done] {e}")
    await c.answer("Заявка отмечена выполненной.",show_alert=True)
    await executor_active(c)

@dp.callback_query(F.data.startswith("order:confirm:"))
async def client_confirm_order(c: CallbackQuery):
    order_id=int(c.data.split(":")[2])
    result=await confirm_order_by_client(order_id,c.from_user.id)
    if not result:
        await c.answer("Заявка уже обработана или недоступна.",show_alert=True); return
    executor_id,payout=result
    await log_order_event(order_id, c.from_user.id, "confirmed", "Клиент подтвердил выполнение")
    await create_notification(executor_id, "order", f"✅ Заявка #{order_id} завершена", "Клиент подтвердил выполнение.", order_id)
    try:
        await c.bot.send_message(executor_id, f"🎉 <b>Заявка #{order_id} подтверждена клиентом.</b>\n\nСредства за заявку зачислены на ваш баланс.", parse_mode="HTML")
    except Exception as e: print(f"[Notify confirm] {e}")
    await c.message.edit_text(f"✅ <b>Заявка #{order_id} завершена.</b>\n\nВыполнение подтверждено.",reply_markup=back(),parse_mode="HTML")
    await c.answer("Заявка завершена")

@dp.callback_query(F.data.startswith("order:dispute:"))
async def client_dispute_order(c: CallbackQuery):
    order_id=int(c.data.split(":")[2])
    executor_id=await dispute_order_by_client(order_id,c.from_user.id)
    if executor_id is None:
        await c.answer("Заявка уже обработана или недоступна.",show_alert=True); return
    await log_order_event(order_id, c.from_user.id, "dispute_opened", "Клиент открыл спор")
    await create_notification(executor_id, "dispute", f"⚖️ Спор по заявке #{order_id}", "Клиент открыл спор.", order_id)
    try:
        await c.bot.send_message(executor_id, f"⚠️ <b>По заявке #{order_id} открыт спор.</b>\n\nСредства остаются в резерве до решения администрации.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💬 Открыть чат",callback_data=f"chat:open:{order_id}")]]), parse_mode="HTML")
    except Exception as e: print(f"[Notify dispute executor] {e}")
    for admin_id in ADMIN_IDS:
        try:
            await c.bot.send_message(admin_id, f"⚠️ <b>Открыт спор по заявке #{order_id}</b>\n\nКлиент: <code>{c.from_user.id}</code>\nИсполнитель: <code>{executor_id}</code>", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⚖️ Открыть спор",callback_data=f"adm:dispute:{order_id}")]]), parse_mode="HTML")
        except Exception as e: print(f"[Dispute admin notify] {e}")
    await c.message.edit_text(f"⚠️ <b>Заявка #{order_id} передана в спор.</b>\n\nСредства остаются в резерве. Администрация рассмотрит ситуацию.",reply_markup=back(),parse_mode="HTML")
    await c.answer("Спор открыт")

@dp.callback_query(F.data == "exec:myorders")
async def executor_my_orders(c: CallbackQuery):
    u = await get_user(c.from_user.id)
    if not u or u[3] != "executor" or u[8]:
        await c.answer("Доступ запрещён.", show_alert=True)
        return
    from .db import get_executor_orders
    rows = await get_executor_orders(c.from_user.id)
    text = "📋 <b>Мои заявки исполнителя</b>\n\n"
    kb = []
    if not rows:
        text += "Заявок пока нет."
    else:
        for x in rows:
            text += f"#{x[0]} — {escape(x[1])}\nПеревод: {float(x[2]):.2f} RUB → Получено: {float(x[3]):.4f} USDT | {ORDER_STATUS_LABELS.get(x[4], x[4])}\n\n"
            if x[4] in ("in_progress", "awaiting_confirmation", "disputed"):
                kb.append([InlineKeyboardButton(
                    text=f"💬 Чат по заявке #{x[0]}",
                    callback_data=f"chat:open:{x[0]}"
                )])
    kb.append([InlineKeyboardButton(text="⬅️ Кабинет", callback_data="executor")])
    await c.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
    await c.answer()

@dp.callback_query(F.data == "exec:active")
async def executor_active(c: CallbackQuery):
    u = await get_user(c.from_user.id)
    if not u or u[3] != "executor" or u[8]:
        await c.answer("Доступ запрещён.", show_alert=True)
        return
    o = await get_executor_active_order(c.from_user.id)
    if not o:
        await c.answer("Активной заявки нет.", show_alert=True)
        return
    status = ORDER_STATUS_LABELS.get(o[6], o[6])
    text = (f"🔧 <b>Активная заявка #{o[0]}</b>\n\n"
            f"Услуга: <b>{escape(o[1])}</b>\n"
            f"Вы переводите: <b>{float(o[2]):.2f} RUB</b>\n"
            f"На баланс получите: <b>{(float(o[3]) + float(o[5])):.4f} USDT</b>\n"
            f"Статус: {status}")
    rows=[]
    if o[6] in ("in_progress", "awaiting_confirmation", "disputed"):
        unread = await get_chat_unread_count(o[0], c.from_user.id)
        label = f"💬 Открыть чат 🔴 {unread}" if unread else "💬 Открыть чат"
        rows.append([InlineKeyboardButton(text=label, callback_data=f"chat:open:{o[0]}")])
    if o[6] == "in_progress":
        rows.append([InlineKeyboardButton(text="✅ Отметить выполненной", callback_data=f"exec:done:{o[0]}")])
    rows.append([InlineKeyboardButton(text="⬅️ ЛК Исполнителя", callback_data="executor")])
    await c.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), parse_mode="HTML")
    await c.answer()

@dp.callback_query(F.data == "exec:history")
async def executor_history(c: CallbackQuery):
    u=await get_user(c.from_user.id)
    if not u or u[3]!="executor" or u[8]:
        await c.answer("Доступ запрещён.",show_alert=True); return
    rows=await get_executor_history(c.from_user.id)
    text="📋 <b>История заявок</b>\n\n"
    if not rows:
        text+="История пока пуста."
    else:
        for x in rows:
            if x[4]=="done" and x[5]=="executor": status="⚖️ Спор закрыт в вашу пользу"
            elif x[4]=="cancelled" and x[5]=="client": status="⚖️ Спор закрыт в пользу клиента"
            elif x[4]=="done": status="✅ Успешно"
            else: status="❌ Отменена"
            text+=(f"<b>#{x[0]} — {escape(x[1])}</b>\n"
                   f"Перевод: {float(x[2]):.2f} RUB → Получено: {float(x[3]):.4f} USDT\n"
                   f"{status}\n\n")
    await c.message.edit_text(text,reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ ЛК Исполнителя",callback_data="executor")]]),parse_mode="HTML"); await c.answer()

@dp.callback_query(F.data == "exec:balance")
async def executor_balance(c: CallbackQuery):
    u=await get_user(c.from_user.id)
    if not u or u[3] != "executor" or u[8]:
        await c.answer("Доступ запрещён.", show_alert=True)
        return
    await c.message.edit_text(f"💰 <b>Баланс исполнителя</b>\n\n<b>{float(u[2]):.4f} USDT</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💸 Вывести", callback_data="exec:withdraw")],
        [InlineKeyboardButton(text="⬅️ ЛК Исполнителя", callback_data="executor")],
    ]), parse_mode="HTML")
    await c.answer()

@dp.callback_query(F.data == "exec:withdraw")
async def executor_withdraw_start(c: CallbackQuery, state: FSMContext):
    u=await get_user(c.from_user.id)
    if not u or u[3] != "executor" or u[8]:
        await c.answer("Доступ запрещён.", show_alert=True)
        return
    await state.clear()
    await state.set_state(UserStates.withdrawal_amount)
    await c.message.edit_text("💸 <b>Вывод средств</b>\n\nВведите сумму в USDT:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ ЛК Исполнителя", callback_data="executor")]]), parse_mode="HTML")
    await c.answer()

@dp.message(UserStates.withdrawal_amount)
async def executor_withdraw_amount(m: Message, state: FSMContext):
    try:
        amount=float((m.text or "").strip().replace(",", "."))
    except ValueError:
        await m.answer("Введите сумму числом, например 25.5")
        return
    if amount <= 0:
        await m.answer("Сумма должна быть больше нуля.")
        return
    u=await get_user(m.from_user.id)
    if not u or u[3] != "executor" or u[8]:
        await state.clear(); await m.answer("Доступ запрещён.", reply_markup=back()); return
    if amount > float(u[2]) + 1e-9:
        await m.answer(f"❌ Недостаточно средств. Доступно: {float(u[2]):.4f} USDT")
        return
    wid,result=await create_withdrawal_request(m.from_user.id, amount)
    await state.clear()
    messages={
        "pending_exists":"⏳ У вас уже есть заявка на вывод, ожидающая обработки.",
        "insufficient_balance":"❌ Недостаточно средств.",
        "invalid":"❌ Некорректные данные.",
    }
    if result != "ok":
        await m.answer(messages.get(result,"❌ Не удалось создать заявку на вывод."), reply_markup=back())
        return
    await m.answer(f"💸 <b>Заявка на вывод #{wid} создана.</b>\n\nСумма: <b>{amount:.4f} USDT</b>\nСтатус: <b>На обработке</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ ЛК Исполнителя", callback_data="executor")]]), parse_mode="HTML")
    from .admin import notify_new_withdrawal
    await notify_new_withdrawal(wid, m.bot)

@dp.callback_query(F.data.startswith("exec:availability:"))
async def executor_availability(c: CallbackQuery):
    value = c.data.split(":")[2] == "1"
    u = await get_user(c.from_user.id)
    if not u or u[3] != "executor" or u[8]:
        await c.answer("Доступ исполнителя заблокирован.", show_alert=True)
        return
    from .db import set_executor_available
    await set_executor_available(c.from_user.id, value)
    active = await get_executor_active_order(c.from_user.id)
    u = await get_user(c.from_user.id)
    await c.message.edit_text(
        f"🧑‍💼 <b>ЛК Исполнителя</b>\n\nСтатус: {'🟢 Доступен' if value else '🔴 Не доступен'}\nБаланс: {float(u[2]):.4f} USDT",
        reply_markup=executor_cabinet_kb(value, bool(active)), parse_mode="HTML")
    await c.answer("Статус обновлён")

@dp.callback_query(F.data == "notifications")
async def notifications(c: CallbackQuery):
    rows = await get_notifications(c.from_user.id, 30)
    await mark_notifications_read(c.from_user.id)
    text = "🔔 <b>Уведомления</b>\n\n"
    kb=[]
    if not rows:
        text += "Уведомлений пока нет."
    else:
        for x in rows:
            when=x[6].strftime("%d.%m %H:%M")
            text += f"<b>{escape(x[3])}</b> — {escape(x[4])}\n{when}\n\n"
            if x[1]:
                kb.append([InlineKeyboardButton(text=f"📋 Заявка #{x[1]}", callback_data=f"order:view:{x[1]}")])
    kb.append([InlineKeyboardButton(text="⬅️ Главное меню", callback_data="back")])
    await safe_edit(c, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await c.answer()

@dp.callback_query(F.data == "support")
async def support(c: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Написать в поддержку", url="https://t.me/tornadopay_suppbot")],
        [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="back")],
    ])
    caption = (
        "🆘 <b>Поддержка TornadoPay</b>\n\n"
        "Если у вас возник вопрос или нужна помощь — наша поддержка всегда на связи.\n\n"
        "📩 Контакт поддержки: @tornadopay_suppbot"
    )
    try:
        await c.message.delete()
    except Exception:
        pass
    try:
        await c.message.answer_photo(
            FSInputFile(SUPPORT_BANNER_PATH),
            caption=caption,
            reply_markup=kb,
            parse_mode="HTML",
        )
    except Exception as e:
        print(f"[support banner] {e}")
        await c.message.answer(caption, reply_markup=kb, parse_mode="HTML")
    await c.answer()

@dp.callback_query(F.data == "back")
async def go_back(c: CallbackQuery, state: FSMContext):
    await state.clear()
    rate = get_exchange_rate()
    u = await get_user(c.from_user.id)
    caption = (
        f"🏠 <b>TornadoPay</b>\n\n"
        f"Выберите раздел:\n\n"
        f"📊 Курс: 1 USDT = {rate:.2f} RUB"
    )
    kb = menu(c.from_user.id, u[3] if u else None)
    # Главное меню всегда должно быть фото-сообщением с баннером, поэтому
    # старое сообщение (текстовое или фото) удаляется и отправляется новое
    # фото-сообщение — так же, как это делает /start.
    try:
        await c.message.delete()
    except Exception:
        pass
    try:
        await c.message.answer_photo(FSInputFile(START_BANNER_PATH), caption=caption, reply_markup=kb, parse_mode="HTML")
    except Exception as e:
        print(f"[start banner] {e}")
        await c.message.answer(caption, reply_markup=kb, parse_mode="HTML")
    await c.answer()

async def main():
    await init_db()

    # Запускаем фоновое обновление курса
    import asyncio
    asyncio.create_task(start_exchange_rate_updater())

    bot = Bot(TOKEN)
    try:
        await dp.start_polling(bot)
    finally:
        await close_db()
