import os
from html import escape

from aiogram import Bot, Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from .db import (
    ORDER_STATUS_LABELS,
    add_service,
    adjust_balance,
    assign_executor,
    find_user,
    get_order,
    get_orders_by_status,
    get_service,
    get_stats,
    get_exchange_rate,
    list_services_admin,
    set_order_status,
    set_service_min_amount,
    set_service_owner_commission,
    set_service_executor_commission,
    toggle_service,
    list_executor_applications, get_executor_application, set_executor_application_question,
    approve_executor_application, reject_executor_application, block_executor, unblock_executor,
    EXECUTOR_APPLICATION_STATUSES,
    settle_order_executor, refund_order_client, get_pending_withdrawals, approve_withdrawal, reject_withdrawal, get_withdrawal, get_disputed_orders, get_recent_chat_messages,
    get_order_events, get_order_evidence, list_executors_admin, set_user_blocked_only, get_all_services_stats, set_service_max_amount, get_service_limits, get_user_blocked, get_user_block_info,
    log_order_event, create_notification, get_service,
)

ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_ID", "").split(",") if x.strip().isdigit()}

admin_router = Router()
admin_router.message.filter(F.from_user.id.in_(ADMIN_IDS))
admin_router.callback_query.filter(F.from_user.id.in_(ADMIN_IDS))


async def notify_new_withdrawal(withdrawal_id, bot: Bot):
    """Уведомляет всех админов о новой заявке на вывод. Раньше эта функция
    отсутствовала, из-за чего запрос на вывод у исполнителя падал с ImportError."""
    w = await get_withdrawal(withdrawal_id)
    if not w:
        return
    text = (
        f"💸 <b>Новая заявка на вывод #{w[0]}</b>\n\n"
        f"Исполнитель: @{w[2] or '—'} (<code>{w[1]}</code>)\n"
        f"Сумма: <b>{float(w[3]):.4f} USDT</b>\n\n"
        "Раздел «💸 Выводы» пока в разработке — обработать вывод можно вручную "
        "через «👤 Пользователь» → корректировка баланса, отдельно списав сумму."
    )
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, parse_mode="HTML")
        except Exception as e:
            print(f"[notify_new_withdrawal] {admin_id}: {e}")


class AdminStates(StatesGroup):
    waiting_service_name = State()
    waiting_service_description = State()
    waiting_service_min_amount = State()
    waiting_service_max_amount = State()
    waiting_service_owner_commission = State()
    waiting_service_executor_commission = State()
    waiting_new_min_amount = State()
    waiting_new_max_amount = State()
    waiting_new_owner_commission = State()
    waiting_new_executor_commission = State()
    waiting_executor_id = State()
    waiting_user_query = State()
    waiting_balance_amount = State()
    waiting_executor_question = State()
    waiting_executor_rejection = State()
    waiting_block_reason = State()
    waiting_emoji_probe = State()


def parse_positive_number(text):
    if not text:
        return None
    text = text.strip().replace(",", ".")
    try:
        value = float(text)
    except ValueError:
        return None
    return value if value > 0 else None


def admin_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Заявки", callback_data="adm:orders:new")],
        [InlineKeyboardButton(text="⚖️ Споры", callback_data="adm:disputes")],
        [InlineKeyboardButton(text="🧑‍💼 Исполнители", callback_data="adm:executors")],
        [InlineKeyboardButton(text="🛒 Услуги", callback_data="adm:services")],
        [InlineKeyboardButton(text="👤 Пользователь", callback_data="adm:user")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="adm:stats")],
        [InlineKeyboardButton(text="💸 Выводы", callback_data="adm:withdrawals")],
    ])


def admin_back_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Админ-меню", callback_data="adm:menu")]
    ])


def user_profile_kb(user_id, is_executor, blocked):
    rows = [
        [InlineKeyboardButton(text="➕ Начислить", callback_data=f"adm:bal:{user_id}:1"),
         InlineKeyboardButton(text="➖ Списать", callback_data=f"adm:bal:{user_id}:-1")],
        [InlineKeyboardButton(
            text=("🔓 Разблокировать" if blocked else "🚫 Заблокировать"),
            callback_data=f"adm:userblock:{user_id}:{0 if blocked else 1}")],
    ]
    if is_executor:
        rows.append([InlineKeyboardButton(text="🧑‍💼 Карточка исполнителя", callback_data=f"adm:executorview:{user_id}")])
    rows.append([InlineKeyboardButton(text="⬅️ Админ-меню", callback_data="adm:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@admin_router.message(Command("admin"))
async def admin_entry(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("🛠 <b>Админ-панель</b>", reply_markup=admin_menu_kb(), parse_mode="HTML")


@admin_router.message(Command("emoji_id"))
async def emoji_id_prompt(m: Message, state: FSMContext):
    """Служебная команда для админа: узнать custom_emoji_id премиум-эмодзи,
    чтобы использовать их на кнопках (InlineKeyboardButton.icon_custom_emoji_id)."""
    if m.from_user.id not in ADMIN_IDS:
        return
    await state.set_state(AdminStates.waiting_emoji_probe)
    await m.answer(
        "Отправьте следующим сообщением текст с нужными премиум-эмодзи "
        "(вставьте их из вкладки Premium в панели эмодзи Telegram, обычные "
        "юникод-смайлы не подойдут) — пришлю их custom_emoji_id.",
    )


@admin_router.message(AdminStates.waiting_emoji_probe)
async def emoji_id_capture(m: Message, state: FSMContext):
    if m.from_user.id not in ADMIN_IDS:
        return
    await state.clear()
    entities = m.entities or []
    found = [e for e in entities if e.type == "custom_emoji"]
    if not found:
        await m.answer(
            "В сообщении не найдено премиум-эмодзи. Убедитесь, что вставили "
            "эмодзи именно из вкладки Premium, и повторите /emoji_id."
        )
        return
    lines = []
    for e in found:
        piece = (m.text or "")[e.offset:e.offset + e.length]
        lines.append(f"{escape(piece)} → <code>{e.custom_emoji_id}</code>")
    await m.answer("Найденные custom_emoji_id:\n\n" + "\n".join(lines), parse_mode="HTML")


@admin_router.callback_query(F.data == "adm:menu")
async def admin_menu_cb(c: CallbackQuery, state: FSMContext):
    await state.clear()
    text, kb = "🛠 <b>Админ-панель</b>", admin_menu_kb()
    if c.message.photo:
        # Сюда можно попасть прямо с фото-меню после /start — фото-сообщение
        # нельзя отредактировать как текстовое, поэтому отправляем новое.
        try:
            await c.message.delete()
        except Exception:
            pass
        await c.message.answer(text, reply_markup=kb, parse_mode="HTML")
    else:
        await c.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await c.answer()


# ---------- Заявки ----------

STATUS_TABS = [
    ("new", "🆕 Новые"),
    ("in_progress", "🔧 В работе"),
    ("awaiting_confirmation", "⏳ На подтверждении"),
    ("disputed", "⚠️ Споры"),
    ("done", "✅ Готовые"),
    ("cancelled", "❌ Отменённые"),
]


def orders_tabs_rows(active_status):
    buttons = [
        InlineKeyboardButton(
            text=("• " if s == active_status else "") + label,
            callback_data=f"adm:orders:{s}",
        )
        for s, label in STATUS_TABS
    ]
    return [buttons[:2], buttons[2:]]


@admin_router.callback_query(F.data.startswith("adm:orders:"))
async def admin_orders(c: CallbackQuery, state: FSMContext):
    await state.clear()
    status = c.data.split(":")[2]
    rows = await get_orders_by_status(status)
    kb = orders_tabs_rows(status)
    for o in rows:
        kb.append([InlineKeyboardButton(
            text=f"#{o[0]} — {o[3]} — {o[4]:.0f} RUB ({o[5]:.4f} USDT) — @{o[2] or o[1]}",
            callback_data=f"adm:order:{o[0]}",
        )])
    kb.append([InlineKeyboardButton(text="⬅️ Админ-меню", callback_data="adm:menu")])
    status_label = dict(STATUS_TABS)[status]
    text = f"📋 <b>Заявки: {status_label}</b>\n\n"
    text += "Заявок нет." if not rows else "Выберите заявку для просмотра:"
    await c.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
    await c.answer()


def render_order_detail(o):
    owner_comm = float(o[7])
    executor_comm = float(o[8])
    user_amount_usdt = float(o[5])
    executor_gets_usdt = float(o[6])
    amount_rub = float(o[4])

    payment_method = o[12]
    payment_details = o[13]
    payment_file_id = o[14]
    if payment_method == "qr_photo":
        payment_text = "📷 Фото QR-кода загружено"
    elif payment_method == "qr_link":
        payment_text = f"🔗 {escape(payment_details or '—')}"
    elif payment_method == "card":
        payment_text = f"<code>{escape(payment_details or '—')}</code>"
    elif payment_method == "phone":
        payment_text = f"<code>{escape(payment_details or '—')}</code>"
    else:
        payment_text = "—"

    text = (
        f"🧾 <b>Заявка #{o[0]}</b>\n\n"
        f"Клиент: @{o[2] or '—'} (<code>{o[1]}</code>)\n"
        f"Услуга: {o[3]}\n\n"
        f"<b>Сумма в рублях:</b> {amount_rub:.2f} RUB\n"
        f"<b>Сумма в USDT:</b> {user_amount_usdt:.4f} USDT\n\n"
        f"<b>Реквизиты для перевода:</b>\n{payment_text}\n\n"
        f"<b>Разбор:</b>\n"
        f"Вам (комиссия): {owner_comm:.4f} USDT\n"
        f"Исполнителю: {executor_gets_usdt:.4f} USDT\n\n"
        f"Статус: {ORDER_STATUS_LABELS.get(o[9], o[9])}\n"
        f"Исполнитель: {o[10] or '—'}\n"
        f"Создана: {o[11]:%d.%m.%Y %H:%M}"
    )
    buttons = []
    if o[9] == "new":
        buttons.append([InlineKeyboardButton(text="🔧 Взять в работу", callback_data=f"adm:ordstatus:{o[0]}:in_progress")])
    if o[9] == "in_progress":
        buttons.append([InlineKeyboardButton(text="✅ Отметить выполненной", callback_data=f"adm:ordstatus:{o[0]}:awaiting_confirmation")])
    if o[9] == "awaiting_confirmation":
        buttons.append([InlineKeyboardButton(text="💸 Выпустить оплату исполнителю", callback_data=f"adm:settle:{o[0]}:executor")])
        buttons.append([InlineKeyboardButton(text="⚠️ Открыть спор", callback_data=f"adm:settle:{o[0]}:dispute")])
    if o[9] == "disputed":
        buttons.append([InlineKeyboardButton(text="👷 В пользу исполнителя", callback_data=f"adm:settle:{o[0]}:executor")])
        buttons.append([InlineKeyboardButton(text="👤 Вернуть клиенту", callback_data=f"adm:settle:{o[0]}:client")])
    if o[9] in ("in_progress", "awaiting_confirmation", "disputed") and o[10]:
        buttons.append([InlineKeyboardButton(text="💬 История чата", callback_data=f"adm:chat:{o[0]}")])
    if o[9] in ("new", "in_progress"):
        buttons.append([InlineKeyboardButton(text="❌ Отменить", callback_data=f"adm:ordstatus:{o[0]}:cancelled")])
        buttons.append([InlineKeyboardButton(text="👷 Назначить исполнителя", callback_data=f"adm:ordexec:{o[0]}")])
    buttons.append([InlineKeyboardButton(text="⬅️ К списку", callback_data=f"adm:orders:{o[9]}")])
    return text, InlineKeyboardMarkup(inline_keyboard=buttons)


@admin_router.callback_query(F.data.startswith("adm:order:"))
async def admin_order_detail(c: CallbackQuery, state: FSMContext):
    await state.clear()
    order_id = int(c.data.split(":")[2])
    o = await get_order(order_id)
    if not o:
        await c.answer("Заявка не найдена", show_alert=True)
        return
    text, kb = render_order_detail(o)
    await c.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await c.answer()


@admin_router.callback_query(F.data.startswith("adm:chat:"))
async def admin_chat_history(c: CallbackQuery, state: FSMContext):
    await state.clear()
    order_id = int(c.data.split(":")[2])
    o = await get_order(order_id)
    if not o or o[9] not in ("in_progress", "awaiting_confirmation", "disputed") or not o[10]:
        await c.answer("История чата недоступна.", show_alert=True)
        return

    rows = await get_recent_chat_messages(order_id, 50)
    rows = list(reversed(rows))
    lines = [f"💬 <b>История чата по заявке #{order_id}</b>", ""]
    if not rows:
        lines.append("Сообщений пока нет.")
    else:
        for r in rows:
            sender_id, content_type, text_content, created_at = r[1], r[2], r[3], r[4]
            if sender_id == o[1]:
                who = "👤 Клиент"
            elif sender_id == o[10]:
                who = "🧑‍💼 Исполнитель"
            else:
                who = f"ID {sender_id}"
            stamp = created_at.strftime("%d.%m.%Y %H:%M") if created_at else ""
            if content_type == "text":
                body = escape(text_content or "")[:1200]
            else:
                body = f"[{escape(content_type)}]"
                if text_content:
                    body += f" {escape(text_content[:500])}"
            lines.append(f"<b>{who}</b> <i>{stamp}</i>:\n{body}")

    if len(lines) > 45:
        # Telegram has a message-size limit; keep the most recent part in the admin view.
        lines = lines[:2] + ["⚠️ Показаны последние сообщения из истории.", ""] + lines[-42:]
    text = "\n\n".join(lines)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 К заявке", callback_data=f"adm:order:{order_id}")],
        [InlineKeyboardButton(text="⚖️ Открыть спор", callback_data=f"adm:order:{order_id}")],
    ])
    # For an already disputed order, the order card contains the verdict buttons.
    await c.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await c.answer()


@admin_router.callback_query(F.data.startswith("adm:ordstatus:"))
async def admin_order_status(c: CallbackQuery):
    _, _, order_id, new_status = c.data.split(":")
    await set_order_status(int(order_id), new_status)
    await log_order_event(int(order_id), c.from_user.id, "status_changed", f"Администратор изменил статус на {new_status}")
    o = await get_order(int(order_id))
    text, kb = render_order_detail(o)
    await c.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await c.answer("Обновлено")


@admin_router.callback_query(F.data.startswith("adm:ordexec:"))
async def admin_order_exec_start(c: CallbackQuery, state: FSMContext):
    order_id = int(c.data.split(":")[2])
    await state.update_data(order_id=order_id)
    await state.set_state(AdminStates.waiting_executor_id)
    await c.message.edit_text(
        "👷 Пришлите Telegram ID исполнителя одним сообщением.",
        reply_markup=admin_back_kb(), parse_mode="HTML")
    await c.answer()


@admin_router.message(AdminStates.waiting_executor_id)
async def admin_order_exec_finish(m: Message, state: FSMContext):
    if not m.text or not m.text.strip().isdigit():
        await m.answer("Нужно число — Telegram ID исполнителя. Попробуйте ещё раз.")
        return
    data = await state.get_data()
    order_id = data["order_id"]
    await assign_executor(order_id, int(m.text.strip()))
    await state.clear()
    o = await get_order(order_id)
    text, kb = render_order_detail(o)
    await m.answer("✅ Исполнитель назначен.\n\n" + text, reply_markup=kb, parse_mode="HTML")


@admin_router.callback_query(F.data.startswith("adm:settle:"))
async def admin_settle(c: CallbackQuery):
    _, _, order_id, action = c.data.split(":")
    order_id = int(order_id)
    if action == "executor":
        result = await settle_order_executor(order_id)
        msg = "Оплата выпущена исполнителю." if result else "Заявка уже обработана или не готова к выплате."
        if result:
            executor_id, payout = result
            try:
                await c.bot.send_message(executor_id, f"🎉 <b>Заявка #{order_id} завершена администрацией</b>\n\nВам начислено <b>{payout:.4f} USDT</b>.", parse_mode="HTML")
            except Exception as e: print(f"[Admin payout notify] {e}")
    elif action == "client":
        result = await refund_order_client(order_id)
        msg = "Средства возвращены клиенту." if result else "Заявка уже обработана или не находится в споре."
        if result:
            client_id, refund = result
            try:
                await c.bot.send_message(client_id, f"💸 <b>По заявке #{order_id} средства возвращены</b>\n\nВозвращено: <b>{refund:.4f} USDT</b>.", parse_mode="HTML")
            except Exception as e: print(f"[Admin refund notify] {e}")
    else:
        from .db import dispute_order_by_admin
        result = await dispute_order_by_admin(order_id)
        msg = "Заявка переведена в спор." if result else "Не удалось открыть спор."
    if result:
        await log_order_event(order_id, c.from_user.id, "admin_decision", msg)
        try:
            if action == "executor" and isinstance(result, tuple):
                await create_notification(result[0], "order", f"⚖️ Заявка #{order_id} закрыта", "Решение администрации: в пользу исполнителя.", order_id)
            elif action == "client" and isinstance(result, tuple):
                await create_notification(result[0], "order", f"⚖️ Заявка #{order_id} закрыта", "Решение администрации: в пользу клиента.", order_id)
        except Exception as e: print(f"[Decision notify] {e}")
    await c.answer(msg, show_alert=True)
    o = await get_order(order_id)
    if o:
        text, kb = render_order_detail(o)
        await c.message.edit_text(text, reply_markup=kb, parse_mode="HTML")

# ---------- Управление исполнителями ----------

@admin_router.callback_query(F.data == "adm:executors")
async def admin_executors(c: CallbackQuery):
    rows=await list_executors_admin(50)
    kb=[]
    for r in rows:
        status="🚫" if r[4] else ("🟢" if r[3] else "🔴")
        kb.append([InlineKeyboardButton(text=f"{status} {r[2] or r[0]} · ⭐ {float(r[7]):.2f} · ✅ {r[6]}", callback_data=f"adm:executorview:{r[0]}")])
    kb.append([InlineKeyboardButton(text="⬅️ Админ-меню",callback_data="adm:menu")])
    await c.message.edit_text("🧑‍💼 <b>Исполнители</b>\n\nВыберите исполнителя:",reply_markup=InlineKeyboardMarkup(inline_keyboard=kb),parse_mode="HTML"); await c.answer()

@admin_router.callback_query(F.data.startswith("adm:executorview:"))
async def admin_executor_view(c: CallbackQuery):
    uid=int(c.data.split(":")[2]); r=next((x for x in await list_executors_admin(100) if x[0]==uid),None)
    if not r:
        await c.answer("Исполнитель не найден",show_alert=True); return
    blocked=bool(r[4])
    text=(f"🧑‍💼 <b>Исполнитель</b>\n\nID: <code>{r[0]}</code>\n"
          f"Имя: {escape(r[2] or '—')}\n"
          f"Username: @{r[1] or '—'}\n"
          f"Статус: {'🚫 Заблокирован' if blocked else ('🟢 Доступен' if r[3] else '🔴 Не доступен')}\n"
          f"⭐ Рейтинг: <b>{float(r[7]):.2f}</b> ({r[8]})\n"
          f"✅ Выполнено: <b>{r[6]}</b>\n"
          f"💰 Баланс: <b>{float(r[5]):.4f} USDT</b>")
    kb=[[InlineKeyboardButton(text=("🔓 Разблокировать" if blocked else "🚫 Заблокировать"),callback_data=f"adm:userblock:{uid}:{0 if blocked else 1}")], [InlineKeyboardButton(text="⬅️ Исполнители",callback_data="adm:executors")]]
    await c.message.edit_text(text,reply_markup=InlineKeyboardMarkup(inline_keyboard=kb),parse_mode="HTML"); await c.answer()

@admin_router.callback_query(F.data.startswith("adm:userblock:"))
async def admin_user_block_start(c: CallbackQuery, state: FSMContext):
    _,_,uid,action=c.data.split(":"); uid=int(uid)
    if action == "0":
        await set_user_blocked_only(uid, False)
        await c.answer("Пользователь разблокирован.")
        u=await find_user(str(uid))
        if u:
            await c.message.edit_text(f"👤 <b>Пользователь</b>\n\nID: <code>{u[0]}</code>\nUsername: @{u[1] or '—'}\nБаланс: {float(u[2]):.4f} USDT\nРоль: {u[3]}\nСтатус: 🟢 Активен", reply_markup=user_profile_kb(u[0],u[3]=='executor',False),parse_mode="HTML")
        return
    await state.update_data(target_user_id=uid)
    await state.set_state(AdminStates.waiting_block_reason)
    await c.message.edit_text("🚫 <b>Блокировка пользователя</b>\n\nУкажите причину блокировки или отправьте «-», чтобы оставить причину пустой.",reply_markup=admin_back_kb(),parse_mode="HTML")
    await c.answer()

@admin_router.message(AdminStates.waiting_block_reason)
async def admin_user_block_finish(m: Message, state: FSMContext):
    data=await state.get_data(); uid=int(data["target_user_id"]); raw=(m.text or '').strip(); reason='' if raw=='-' else raw
    await set_user_blocked_only(uid, True, reason)
    await state.clear()
    await m.answer("🚫 Пользователь заблокирован.",reply_markup=admin_back_kb())
    try:
        await m.bot.send_message(uid, "🚫 <b>Ваш аккаунт заблокирован администрацией.</b>" + (f"\n\nПричина: {escape(reason)}" if reason else ""),parse_mode="HTML")
    except Exception as e: print(f"[Block notify] {e}")

@admin_router.callback_query(F.data == "adm:user")
async def admin_user_start(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(AdminStates.waiting_user_query)
    await c.message.edit_text(
        "👤 Пришлите Telegram ID или @username пользователя.",
        reply_markup=admin_back_kb(), parse_mode="HTML")
    await c.answer()


def render_user_profile(u):
    blocked = bool(u[5])
    text = (
        f"👤 <b>Пользователь</b>\n\n"
        f"ID: <code>{u[0]}</code>\n"
        f"Username: @{u[1] or '—'}\n"
        f"Баланс: {float(u[2]):.4f} USDT\n"
        f"Роль: {u[3]}\n"
        f"Статус: {'🚫 Заблокирован' + (f' ({escape(u[6])})' if u[6] else '') if blocked else '🟢 Активен'}"
    )
    return text, user_profile_kb(u[0], u[3] == "executor", blocked)


@admin_router.message(AdminStates.waiting_user_query)
async def admin_user_search(m: Message, state: FSMContext):
    u = await find_user(m.text or "")
    if not u:
        await m.answer("Пользователь не найден. Пришлите ID или @username ещё раз.")
        return
    await state.clear()
    text, kb = render_user_profile(u)
    await m.answer(text, reply_markup=kb, parse_mode="HTML")


@admin_router.callback_query(F.data.startswith("adm:bal:"))
async def admin_balance_start(c: CallbackQuery, state: FSMContext):
    _, _, user_id, sign = c.data.split(":")
    await state.update_data(target_user_id=int(user_id), sign=int(sign))
    await state.set_state(AdminStates.waiting_balance_amount)
    action = "начисления" if sign == "1" else "списания"
    await c.message.edit_text(
        f"Пришлите сумму для {action} числом.",
        reply_markup=admin_back_kb(), parse_mode="HTML")
    await c.answer()


@admin_router.message(AdminStates.waiting_balance_amount)
async def admin_balance_finish(m: Message, state: FSMContext):
    amount = parse_positive_number(m.text)
    if amount is None:
        await m.answer("Нужно положительное число. Попробуйте ещё раз.")
        return
    data = await state.get_data()
    delta = amount * data["sign"]
    target_id = data["target_user_id"]
    new_balance = await adjust_balance(target_id, delta)
    await state.clear()
    u = await find_user(str(target_id))
    if u:
        text, kb = render_user_profile(u)
        await m.answer("✅ Баланс обновлён.\n\n" + text, reply_markup=kb, parse_mode="HTML")
    else:
        await m.answer("✅ Баланс обновлён.", reply_markup=admin_back_kb())
    if new_balance is not None:
        sign = "+" if delta > 0 else "-"
        try:
            await m.bot.send_message(
                target_id,
                f"💳 Администратор изменил ваш баланс: {sign}{amount:.4f} USDT.\n"
                f"Текущий баланс: {float(new_balance):.4f} USDT",
            )
        except Exception as e:
            print(f"[Balance notify] {e}")


# ---------- Услуги ----------

def services_list_kb(rows):
    kb = []
    for s in rows:
        mark = "✅" if s[6] else "🚫"
        kb.append([InlineKeyboardButton(text=f"{mark} {s[1]}", callback_data=f"adm:svc:{s[0]}")])
    kb.append([InlineKeyboardButton(text="➕ Добавить услугу", callback_data="adm:svcadd")])
    kb.append([InlineKeyboardButton(text="⬅️ Админ-меню", callback_data="adm:menu")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


@admin_router.callback_query(F.data == "adm:services")
async def admin_services(c: CallbackQuery, state: FSMContext):
    await state.clear()
    rows = await list_services_admin()
    await c.message.edit_text(
        "🛒 <b>Услуги</b>\n\nВыберите услугу или добавьте новую:",
        reply_markup=services_list_kb(rows), parse_mode="HTML")
    await c.answer()


def render_service_detail(s):
    status = "активна" if s[6] else "отключена"
    text = (
        f"🛒 <b>{s[1]}</b>\n\n{s[2] or '—'}\n\n"
        f"Мин. сумма: {float(s[3]):.2f} USDT\n"
        f"Макс. сумма: {float(s[7]):.2f} USDT\n"
        f"Комиссия платформы: {float(s[4]):.2f}%\n"
        f"Комиссия исполнителя: {float(s[5]):.2f}%\n"
        f"Статус: {status}"
    )
    toggle_text = "🚫 Деактивировать" if s[6] else "✅ Активировать"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=toggle_text, callback_data=f"adm:svctoggle:{s[0]}")],
        [InlineKeyboardButton(text="💲 Мин. сумма", callback_data=f"adm:svcmin:{s[0]}"),
         InlineKeyboardButton(text="💲 Макс. сумма", callback_data=f"adm:svcmax:{s[0]}")],
        [InlineKeyboardButton(text="⚙️ Комиссия платформы", callback_data=f"adm:svcowncomm:{s[0]}")],
        [InlineKeyboardButton(text="⚙️ Комиссия исполнителя", callback_data=f"adm:svcexeccomm:{s[0]}")],
        [InlineKeyboardButton(text="⬅️ К услугам", callback_data="adm:services")],
    ])
    return text, kb


@admin_router.callback_query(F.data.startswith("adm:svc:"))
async def admin_service_detail(c: CallbackQuery, state: FSMContext):
    await state.clear()
    sid = int(c.data.split(":")[2])
    s = await get_service(sid)
    if not s:
        await c.answer("Услуга не найдена", show_alert=True)
        return
    text, kb = render_service_detail(s)
    await c.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await c.answer()


@admin_router.callback_query(F.data.startswith("adm:svctoggle:"))
async def admin_service_toggle(c: CallbackQuery):
    sid = int(c.data.split(":")[2])
    await toggle_service(sid)
    s = await get_service(sid)
    text, kb = render_service_detail(s)
    await c.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await c.answer("Обновлено")


_SERVICE_FIELD_EDIT = {
    "adm:svcmin:": (AdminStates.waiting_new_min_amount, set_service_min_amount, "минимальную сумму (USDT)"),
    "adm:svcmax:": (AdminStates.waiting_new_max_amount, set_service_max_amount, "максимальную сумму (USDT)"),
    "adm:svcowncomm:": (AdminStates.waiting_new_owner_commission, set_service_owner_commission, "комиссию платформы (%)"),
    "adm:svcexeccomm:": (AdminStates.waiting_new_executor_commission, set_service_executor_commission, "комиссию исполнителя (%)"),
}


@admin_router.callback_query(F.data.startswith(("adm:svcmin:", "adm:svcmax:", "adm:svcowncomm:", "adm:svcexeccomm:")))
async def admin_service_field_start(c: CallbackQuery, state: FSMContext):
    prefix = next(p for p in _SERVICE_FIELD_EDIT if c.data.startswith(p))
    target_state, _, label = _SERVICE_FIELD_EDIT[prefix]
    sid = int(c.data.split(":")[2])
    await state.update_data(service_id=sid, field_prefix=prefix)
    await state.set_state(target_state)
    await c.message.edit_text(f"Пришлите новое значение — {label}.", reply_markup=admin_back_kb())
    await c.answer()


async def _admin_service_field_finish(m: Message, state: FSMContext):
    value = parse_positive_number(m.text)
    if value is None:
        await m.answer("Нужно положительное число. Попробуйте ещё раз.")
        return
    data = await state.get_data()
    prefix = data["field_prefix"]
    sid = data["service_id"]
    _, setter, _ = _SERVICE_FIELD_EDIT[prefix]
    await setter(sid, value)
    await state.clear()
    s = await get_service(sid)
    text, kb = render_service_detail(s)
    await m.answer("✅ Значение обновлено.\n\n" + text, reply_markup=kb, parse_mode="HTML")


@admin_router.message(AdminStates.waiting_new_min_amount)
async def admin_service_min_finish(m: Message, state: FSMContext):
    await _admin_service_field_finish(m, state)


@admin_router.message(AdminStates.waiting_new_max_amount)
async def admin_service_max_finish(m: Message, state: FSMContext):
    await _admin_service_field_finish(m, state)


@admin_router.message(AdminStates.waiting_new_owner_commission)
async def admin_service_owncomm_finish(m: Message, state: FSMContext):
    await _admin_service_field_finish(m, state)


@admin_router.message(AdminStates.waiting_new_executor_commission)
async def admin_service_execcomm_finish(m: Message, state: FSMContext):
    await _admin_service_field_finish(m, state)


@admin_router.callback_query(F.data == "adm:svcadd")
async def admin_service_add_start(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(AdminStates.waiting_service_name)
    await c.message.edit_text("➕ Пришлите название новой услуги.", reply_markup=admin_back_kb())
    await c.answer()


@admin_router.message(AdminStates.waiting_service_name)
async def admin_service_add_name(m: Message, state: FSMContext):
    if not m.text or not m.text.strip():
        await m.answer("Название не может быть пустым. Попробуйте ещё раз.")
        return
    await state.update_data(name=m.text.strip())
    await state.set_state(AdminStates.waiting_service_description)
    await m.answer("Теперь пришлите описание услуги (или «-», чтобы оставить пустым).")


@admin_router.message(AdminStates.waiting_service_description)
async def admin_service_add_description(m: Message, state: FSMContext):
    raw = (m.text or "").strip()
    await state.update_data(description="" if raw == "-" else raw)
    await state.set_state(AdminStates.waiting_service_min_amount)
    await m.answer("Минимальная сумма заявки в USDT?")


@admin_router.message(AdminStates.waiting_service_min_amount)
async def admin_service_add_min(m: Message, state: FSMContext):
    value = parse_positive_number(m.text)
    if value is None:
        await m.answer("Нужно положительное число. Попробуйте ещё раз.")
        return
    await state.update_data(min_amount=value)
    await state.set_state(AdminStates.waiting_service_max_amount)
    await m.answer("Максимальная сумма заявки в USDT?")


@admin_router.message(AdminStates.waiting_service_max_amount)
async def admin_service_add_max(m: Message, state: FSMContext):
    value = parse_positive_number(m.text)
    if value is None:
        await m.answer("Нужно положительное число. Попробуйте ещё раз.")
        return
    await state.update_data(max_amount=value)
    await state.set_state(AdminStates.waiting_service_owner_commission)
    await m.answer("Комиссия платформы, % (например 5)?")


@admin_router.message(AdminStates.waiting_service_owner_commission)
async def admin_service_add_owncomm(m: Message, state: FSMContext):
    value = parse_positive_number(m.text)
    if value is None:
        await m.answer("Нужно положительное число. Попробуйте ещё раз.")
        return
    await state.update_data(owner_commission=value)
    await state.set_state(AdminStates.waiting_service_executor_commission)
    await m.answer("Комиссия исполнителя, % (например 5)?")


@admin_router.message(AdminStates.waiting_service_executor_commission)
async def admin_service_add_execcomm(m: Message, state: FSMContext):
    value = parse_positive_number(m.text)
    if value is None:
        await m.answer("Нужно положительное число. Попробуйте ещё раз.")
        return
    data = await state.get_data()
    sid = await add_service(data["name"], data["description"], data["min_amount"], data["owner_commission"], value)
    await state.clear()
    await m.answer(f"✅ Услуга «{data['name']}» добавлена (#{sid}).")
    rows = await list_services_admin()
    await m.answer("🛒 <b>Услуги</b>", reply_markup=services_list_kb(rows), parse_mode="HTML")


# ---------- Споры ----------

@admin_router.callback_query(F.data == "adm:disputes")
async def admin_disputes(c: CallbackQuery, state: FSMContext):
    await state.clear()
    rows = await get_disputed_orders()
    kb = []
    for o in rows:
        kb.append([InlineKeyboardButton(
            text=f"#{o[0]} — {o[5]} — {o[7]:.4f} USDT — @{o[2] or o[1]} vs @{o[4] or o[3] or '—'}",
            callback_data=f"adm:order:{o[0]}",
        )])
    kb.append([InlineKeyboardButton(text="⬅️ Админ-меню", callback_data="adm:menu")])
    text = "⚖️ <b>Споры</b>\n\n" + ("Открытых споров нет." if not rows else "Выберите заявку для разбора:")
    await c.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
    await c.answer()


# ---------- Выводы ----------
# Обработка (подтверждение/отклонение) выводов — отдельный следующий этап.
# Пока только список, чтобы админ видел накопившиеся заявки.

@admin_router.callback_query(F.data == "adm:withdrawals")
async def admin_withdrawals(c: CallbackQuery, state: FSMContext):
    await state.clear()
    rows = await get_pending_withdrawals()
    if not rows:
        text = "💸 <b>Выводы</b>\n\nЗаявок на вывод нет."
    else:
        lines = [f"#{w[0]} — @{w[2] or w[1]} (<code>{w[1]}</code>) — {float(w[3]):.4f} USDT" for w in rows]
        text = (
            "💸 <b>Выводы: ожидают обработки</b>\n\n" + "\n".join(lines) +
            "\n\n⚠️ Подтверждение/отклонение выводов ещё не реализовано в этом разделе — "
            "используйте «👤 Пользователь», чтобы вручную скорректировать баланс после выплаты."
        )
    await c.message.edit_text(text, reply_markup=admin_back_kb(), parse_mode="HTML")
    await c.answer()


# ---------- Статистика ----------

@admin_router.callback_query(F.data == "adm:stats")
async def admin_stats(c: CallbackQuery, state: FSMContext):
    await state.clear()
    s = await get_stats()
    rate = get_exchange_rate()
    by_status = s["orders_by_status"]
    lines = [f"{ORDER_STATUS_LABELS.get(k, k)}: {v}" for k, v in by_status.items()]
    text = (
        "📊 <b>Статистика</b>\n\n"
        f"Пользователей: {s['users']}\n"
        f"Активных услуг: {s['active_services']}\n"
        f"Заявок всего: {s['orders']}\n\n"
        f"Текущий курс: 1 USDT = {rate:.2f} RUB\n\n"
        + ("\n".join(lines) if lines else "Заявок пока нет.")
    )
    await c.message.edit_text(text, reply_markup=admin_back_kb(), parse_mode="HTML")
    await c.answer()
