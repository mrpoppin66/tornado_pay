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
    settle_order_executor, refund_order_client, get_pending_withdrawals, approve_withdrawal, reject_withdrawal, get_disputed_orders, get_recent_chat_messages,
    get_order_events, get_order_evidence, list_executors_admin, set_user_blocked_only, get_all_services_stats, set_service_max_amount, get_service_limits, get_user_blocked, get_user_block_info,
    log_order_event, create_notification,
)

ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_ID", "").split(",") if x.strip().isdigit()}

admin_router = Router()
admin_router.message.filter(F.from_user.id.in_(ADMIN_IDS))
admin_router.callback_query.filter(F.from_user.id.in_(ADMIN_IDS))


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


@admin_router.message(Command("admin"))
async def admin_entry(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("🛠 <b>Админ-панель</b>", reply_markup=admin_menu_kb(), parse_mode="HTML")


@admin_router.callback_query(F.data == "adm:menu")
async def admin_menu_cb(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await c.message.edit_text("🛠 <b>Админ-панель</b>", reply_markup=admin_menu_kb(), parse_mode="HTML")
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

    text = (
        f"🧾 <b>Заявка #{o[0]}</b>\n\n"
        f"Клиент: @{o[2] or '—'} (<code>{o[1]}</code>)\n"
        f"Услуга: {o[3]}\n\n"
        f"<b>Сумма в рублях:</b> {amount_rub:.2f} RUB\n"
        f"<b>Сумма в USDT:</b> {user_amount_usdt:.4f} USDT\n\n"
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
    new_balance = await adjust_balance(data["target_user_id"], delta)
    await state.clear()
    await m.answer(
        f"✅ Готово. Новый баланс пользователя <code>{data['target_user_id']}</code>: {new_balance:.2f} USDT",
        reply_markup=admin_back_kb(), parse_mode="HTML")


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
