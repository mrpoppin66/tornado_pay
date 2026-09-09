import os

from aiogram import Router, F
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
    list_services_admin,
    set_order_status,
    set_service_min_amount,
    set_service_owner_commission,
    set_service_executor_commission,
    toggle_service,
)

ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_ID", "").split(",") if x.strip().isdigit()}

admin_router = Router()
admin_router.message.filter(F.from_user.id.in_(ADMIN_IDS))
admin_router.callback_query.filter(F.from_user.id.in_(ADMIN_IDS))


class AdminStates(StatesGroup):
    waiting_service_name = State()
    waiting_service_description = State()
    waiting_service_min_amount = State()
    waiting_service_owner_commission = State()
    waiting_service_executor_commission = State()
    waiting_new_min_amount = State()
    waiting_new_owner_commission = State()
    waiting_new_executor_commission = State()
    waiting_executor_id = State()
    waiting_user_query = State()
    waiting_balance_amount = State()


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
        [InlineKeyboardButton(text="🛒 Услуги", callback_data="adm:services")],
        [InlineKeyboardButton(text="👤 Пользователь", callback_data="adm:user")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="adm:stats")],
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
            text=f"#{o[0]} — {o[3]} — {o[4]:.0f} USDT (итого {o[5]:.0f}) — @{o[2] or o[1]}",
            callback_data=f"adm:order:{o[0]}",
        )])
    kb.append([InlineKeyboardButton(text="⬅️ Админ-меню", callback_data="adm:menu")])
    status_label = dict(STATUS_TABS)[status]
    text = f"📋 <b>Заявки: {status_label}</b>\n\n"
    text += "Заявок нет." if not rows else "Выберите заявку для просмотра:"
    await c.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
    await c.answer()


def render_order_detail(o):
    owner_comm = float(o[6])
    executor_comm = float(o[7])
    text = (
        f"🧾 <b>Заявка #{o[0]}</b>\n\n"
        f"Клиент: @{o[2] or '—'} (<code>{o[1]}</code>)\n"
        f"Услуга: {o[3]}\n"
        f"Сумма услуги: {o[4]:.2f} USDT\n"
        f"Итого к оплате: {o[5]:.2f} USDT\n"
        f"Комиссия вам: {owner_comm:.2f} USDT\n"
        f"Комиссия исполнителю: {executor_comm:.2f} USDT\n"
        f"Статус: {ORDER_STATUS_LABELS.get(o[8], o[8])}\n"
        f"Исполнитель: {o[9] or '—'}\n"
        f"Создана: {o[10]:%d.%m.%Y %H:%M}"
    )
    buttons = []
    if o[8] == "new":
        buttons.append([InlineKeyboardButton(text="🔧 Взять в работу", callback_data=f"adm:ordstatus:{o[0]}:in_progress")])
    if o[8] == "in_progress":
        buttons.append([InlineKeyboardButton(text="✅ Отметить выполненной", callback_data=f"adm:ordstatus:{o[0]}:done")])
    if o[8] in ("new", "in_progress"):
        buttons.append([InlineKeyboardButton(text="❌ Отменить", callback_data=f"adm:ordstatus:{o[0]}:cancelled")])
        buttons.append([InlineKeyboardButton(text="👷 Назначить исполнителя", callback_data=f"adm:ordexec:{o[0]}")])
    buttons.append([InlineKeyboardButton(text="⬅️ К списку", callback_data=f"adm:orders:{o[8]}")])
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


# ---------- Услуги ----------

def services_list_kb(rows):
    kb = []
    for s in rows:
        mark = "✅" if s[6] else "🚫"
        owner_c = float(s[4])
        executor_c = float(s[5])
        total_c = owner_c + executor_c
        kb.append([InlineKeyboardButton(
            text=f"{mark} {s[1]} | мин {s[3]:.2f} | комиссия {total_c:.1f}%",
            callback_data=f"adm:svc:{s[0]}"
        )])
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
    owner_c = float(s[4])
    executor_c = float(s[5])
    total_c = owner_c + executor_c
    text = (
        f"🛒 <b>{s[1]}</b>\n\n"
        f"{s[2] or '—'}\n\n"
        f"Минимальная сумма: {s[3]:.2f} USDT\n"
        f"Комиссия вам: {owner_c:.2f}%\n"
        f"Комиссия исполнителю: {executor_c:.2f}%\n"
        f"Итого комиссия: {total_c:.2f}%\n"
        f"Статус: {status}"
    )
    toggle_text = "🚫 Деактивировать" if s[6] else "✅ Активировать"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=toggle_text, callback_data=f"adm:svctoggle:{s[0]}")],
        [InlineKeyboardButton(text="📏 Мин. сумма", callback_data=f"adm:svcmin:{s[0]}")],
        [InlineKeyboardButton(text="💰 Ваша комиссия", callback_data=f"adm:svcowner:{s[0]}")],
        [InlineKeyboardButton(text="👷 Комиссия испол.", callback_data=f"adm:svcexec:{s[0]}")],
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


# ---------- Минимальная сумма ----------

@admin_router.callback_query(F.data.startswith("adm:svcmin:"))
async def admin_service_min_start(c: CallbackQuery, state: FSMContext):
    sid = int(c.data.split(":")[2])
    await state.update_data(service_id=sid)
    await state.set_state(AdminStates.waiting_new_min_amount)
    await c.message.edit_text(
        "📏 Пришлите новую минимальную сумму числом (например 10 или 5.50).",
        reply_markup=admin_back_kb(), parse_mode="HTML")
    await c.answer()


@admin_router.message(AdminStates.waiting_new_min_amount)
async def admin_service_min_finish(m: Message, state: FSMContext):
    amount = parse_positive_number(m.text)
    if amount is None:
        await m.answer("Нужно положительное число. Попробуйте ещё раз.")
        return
    data = await state.get_data()
    sid = data["service_id"]
    await set_service_min_amount(sid, amount)
    await state.clear()
    s = await get_service(sid)
    text, kb = render_service_detail(s)
    await m.answer("✅ Минимальная сумма обновлена.\n\n" + text, reply_markup=kb, parse_mode="HTML")


# ---------- Комиссия вам (владельцу) ----------

@admin_router.callback_query(F.data.startswith("adm:svcowner:"))
async def admin_service_owner_comm_start(c: CallbackQuery, state: FSMContext):
    sid = int(c.data.split(":")[2])
    await state.update_data(service_id=sid)
    await state.set_state(AdminStates.waiting_new_owner_commission)
    await c.message.edit_text(
        "💰 Пришлите вашу комиссию в процентах (например 5 или 2.5).",
        reply_markup=admin_back_kb(), parse_mode="HTML")
    await c.answer()


@admin_router.message(AdminStates.waiting_new_owner_commission)
async def admin_service_owner_comm_finish(m: Message, state: FSMContext):
    amount = parse_positive_number(m.text)
    if amount is None or amount > 100:
        await m.answer("Нужно число от 0 до 100. Попробуйте ещё раз.")
        return
    data = await state.get_data()
    sid = data["service_id"]
    await set_service_owner_commission(sid, amount)
    await state.clear()
    s = await get_service(sid)
    text, kb = render_service_detail(s)
    await m.answer("✅ Ваша комиссия обновлена.\n\n" + text, reply_markup=kb, parse_mode="HTML")


# ---------- Комиссия исполнителю ----------

@admin_router.callback_query(F.data.startswith("adm:svcexec:"))
async def admin_service_executor_comm_start(c: CallbackQuery, state: FSMContext):
    sid = int(c.data.split(":")[2])
    await state.update_data(service_id=sid)
    await state.set_state(AdminStates.waiting_new_executor_commission)
    await c.message.edit_text(
        "👷 Пришлите комиссию исполнителю в процентах (например 5 или 2.5).",
        reply_markup=admin_back_kb(), parse_mode="HTML")
    await c.answer()


@admin_router.message(AdminStates.waiting_new_executor_commission)
async def admin_service_executor_comm_finish(m: Message, state: FSMContext):
    amount = parse_positive_number(m.text)
    if amount is None or amount > 100:
        await m.answer("Нужно число от 0 до 100. Попробуйте ещё раз.")
        return
    data = await state.get_data()
    sid = data["service_id"]
    await set_service_executor_commission(sid, amount)
    await state.clear()
    s = await get_service(sid)
    text, kb = render_service_detail(s)
    await m.answer("✅ Комиссия исполнителя обновлена.\n\n" + text, reply_markup=kb, parse_mode="HTML")


# ---------- Добавление услуги ----------

@admin_router.callback_query(F.data == "adm:svcadd")
async def admin_service_add_start(c: CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.waiting_service_name)
    await c.message.edit_text(
        "➕ Пришлите название новой услуги.", reply_markup=admin_back_kb())
    await c.answer()


@admin_router.message(AdminStates.waiting_service_name)
async def admin_service_add_name(m: Message, state: FSMContext):
    if not m.text or not m.text.strip():
        await m.answer("Название не может быть пустым. Попробуйте ещё раз.")
        return
    await state.update_data(name=m.text.strip())
    await state.set_state(AdminStates.waiting_service_description)
    await m.answer("Теперь пришлите описание услуги (или отправьте «-», чтобы оставить пустым).")


@admin_router.message(AdminStates.waiting_service_description)
async def admin_service_add_description(m: Message, state: FSMContext):
    raw = (m.text or "").strip()
    desc = "" if raw == "-" else raw
    await state.update_data(description=desc)
    await state.set_state(AdminStates.waiting_service_min_amount)
    await m.answer("Теперь пришлите минимальную сумму заявки (например 10).")


@admin_router.message(AdminStates.waiting_service_min_amount)
async def admin_service_add_min_amount(m: Message, state: FSMContext):
    amount = parse_positive_number(m.text)
    if amount is None:
        await m.answer("Нужно положительное число. Попробуйте ещё раз.")
        return
    await state.update_data(min_amount=amount)
    await state.set_state(AdminStates.waiting_service_owner_commission)
    await m.answer("Теперь пришлите вашу комиссию в процентах (например 5).")


@admin_router.message(AdminStates.waiting_service_owner_commission)
async def admin_service_add_owner_commission(m: Message, state: FSMContext):
    comm = parse_positive_number(m.text)
    if comm is None or comm > 100:
        await m.answer("Нужно число от 0 до 100. Попробуйте ещё раз.")
        return
    await state.update_data(owner_commission=comm)
    await state.set_state(AdminStates.waiting_service_executor_commission)
    await m.answer("Теперь пришлите комиссию исполнителю в процентах (например 5).")


@admin_router.message(AdminStates.waiting_service_executor_commission)
async def admin_service_add_executor_commission(m: Message, state: FSMContext):
    comm = parse_positive_number(m.text)
    if comm is None or comm > 100:
        await m.answer("Нужно число от 0 до 100. Попробуйте ещё раз.")
        return
    data = await state.get_data()
    sid = await add_service(data["name"], data["description"], data["min_amount"],
                           data["owner_commission"], comm)
    await state.clear()
    await m.answer(f"✅ Услуга «{data['name']}» добавлена (#{sid}).")
    rows = await list_services_admin()
    await m.answer("🛒 <b>Услуги</b>", reply_markup=services_list_kb(rows), parse_mode="HTML")


# ---------- Пользователи ----------

def user_profile_kb(user_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Начислить", callback_data=f"adm:bal:{user_id}:1"),
         InlineKeyboardButton(text="➖ Списать", callback_data=f"adm:bal:{user_id}:-1")],
        [InlineKeyboardButton(text="⬅️ Админ-меню", callback_data="adm:menu")],
    ])


@admin_router.callback_query(F.data == "adm:user")
async def admin_user_start(c: CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.waiting_user_query)
    await c.message.edit_text(
        "👤 Пришлите Telegram ID или @username пользователя.",
        reply_markup=admin_back_kb(), parse_mode="HTML")
    await c.answer()


@admin_router.message(AdminStates.waiting_user_query)
async def admin_user_search(m: Message, state: FSMContext):
    u = await find_user(m.text or "")
    if not u:
        await m.answer("Пользователь не найден. Пришлите ID или @username ещё раз.")
        return
    await state.clear()
    text = (
        f"👤 <b>Пользователь</b>\n\nID: <code>{u[0]}</code>\n"
        f"Username: @{u[1] or '—'}\nБаланс: {u[2]:.2f} USDT\nРоль: {u[3]}"
    )
    await m.answer(text, reply_markup=user_profile_kb(u[0]), parse_mode="HTML")


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
    by_status = s["orders_by_status"]
    lines = [f"{ORDER_STATUS_LABELS.get(k, k)}: {v}" for k, v in by_status.items()]
    text = (
        "📊 <b>Статистика</b>\n\n"
        f"Пользователей: {s['users']}\n"
        f"Активных услуг: {s['active_services']}\n"
        f"Заявок всего: {s['orders']}\n\n"
        + ("\n".join(lines) if lines else "Заявок пока нет.")
    )
    await c.message.edit_text(text, reply_markup=admin_back_kb(), parse_mode="HTML")
    await c.answer()
