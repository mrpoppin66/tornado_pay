import os
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv
from .db import (
    init_db, close_db, ensure_user, get_user, get_services, get_service, create_order, 
    get_orders, ORDER_STATUS_LABELS,
)
from .admin import admin_router, ADMIN_IDS

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")

dp = Dispatcher()
dp.include_router(admin_router)

class UserStates(StatesGroup):
    waiting_order_amount = State()

def menu(user_id=None):
    kb = [
        [InlineKeyboardButton(text="💰 Баланс", callback_data="balance"),
         InlineKeyboardButton(text="🛒 Услуги", callback_data="services")],
        [InlineKeyboardButton(text="📋 Мои заявки", callback_data="orders"),
         InlineKeyboardButton(text="👤 Профиль", callback_data="profile")],
        [InlineKeyboardButton(text="🧑‍💼 Стать исполнителем", callback_data="executor"),
         InlineKeyboardButton(text="🆘 Поддержка", callback_data="support")],
    ]
    if user_id in ADMIN_IDS:
        kb.append([InlineKeyboardButton(text="🛠 Админ-панель", callback_data="adm:menu")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def back():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="back")]
    ])

@dp.message(CommandStart())
async def start(m: Message):
    await ensure_user(m.from_user.id, m.from_user.username)
    await m.answer(
        "👋 Добро пожаловать в <b>TornadoPay</b>!\n\n"
        "Маркетплейс услуг с оплатой в криптовалюте.\n"
        "Выберите услугу и укажите сумму — мы рассчитаем комиссию.",
        reply_markup=menu(m.from_user.id), parse_mode="HTML")

@dp.callback_query(F.data == "balance")
async def balance(c: CallbackQuery):
    u = await get_user(c.from_user.id)
    await c.message.edit_text(
        f"💰 <b>Баланс</b>\n\n{u[2]:.2f} USDT\n\n"
        "CryptoBot/xRocket подключим следующим этапом.",
        reply_markup=back(), parse_mode="HTML")
    await c.answer()

@dp.callback_query(F.data == "profile")
async def profile(c: CallbackQuery):
    u = await get_user(c.from_user.id)
    await c.message.edit_text(
        f"👤 <b>Профиль</b>\n\nID: <code>{u[0]}</code>\n"
        f"Username: @{u[1] or '—'}\nБаланс: {u[2]:.2f} USDT\nРоль: {u[3]}",
        reply_markup=back(), parse_mode="HTML")
    await c.answer()

@dp.callback_query(F.data == "services")
async def services(c: CallbackQuery):
    rows = await get_services()
    kb = [[InlineKeyboardButton(text=f"{x[1]} (мин. {x[3]:.2f} USDT)", callback_data=f"svc:{x[0]}")] for x in rows]
    kb.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back")])
    await c.message.edit_text(
        "🛒 <b>Услуги</b>\n\nВыберите услугу:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
    await c.answer()

@dp.callback_query(F.data.startswith("svc:"))
async def service_select(c: CallbackQuery, state: FSMContext):
    sid = int(c.data.split(":")[1])
    service = await get_service(sid)
    if not service:
        await c.answer("Услуга не найдена", show_alert=True)
        return
    
    await state.update_data(service_id=sid, service_name=service[1], 
                           min_amount=float(service[3]), 
                           owner_comm=float(service[4]),
                           executor_comm=float(service[5]))
    await state.set_state(UserStates.waiting_order_amount)
    
    total_comm = float(service[4]) + float(service[5])
    await c.message.edit_text(
        f"🛒 <b>{service[1]}</b>\n\n"
        f"{service[2]}\n\n"
        f"Минимальная сумма: {service[3]:.2f} USDT\n"
        f"Комиссия: {total_comm:.1f}%\n\n"
        f"Пришлите сумму (числом, например 100 или 50.50):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ К услугам", callback_data="services")]
        ]), parse_mode="HTML")
    await c.answer()

@dp.message(UserStates.waiting_order_amount)
async def order_amount(m: Message, state: FSMContext):
    if not m.text:
        await m.answer("Пришлите сумму числом.")
        return
    
    try:
        amount = float(m.text.strip().replace(",", "."))
    except ValueError:
        await m.answer("Неверный формат. Пришлите сумму числом (например 100 или 50.50).")
        return
    
    data = await state.get_data()
    min_amount = float(data["min_amount"])
    
    if amount < min_amount:
        await m.answer(f"❌ Минимальная сумма для этой услуги: {min_amount:.2f} USDT")
        return
    
    # Создаём заявку
    oid = await create_order(m.from_user.id, data["service_id"], amount)
    if not oid:
        await m.answer("❌ Ошибка при создании заявки. Попробуйте ещё раз.")
        await state.clear()
        return
    
    owner_comm = float(data["owner_comm"])
    executor_comm = float(data["executor_comm"])
    total_comm = owner_comm + executor_comm
    commission = amount * (total_comm / 100)
    total_amount = amount + commission
    
    await state.clear()
    await m.answer(
        f"🧾 <b>Заявка #{oid}</b>\n\n"
        f"Услуга: {data['service_name']}\n"
        f"Сумма услуги: {amount:.2f} USDT\n"
        f"Комиссия ({total_comm:.1f}%): {commission:.2f} USDT\n"
        f"<b>Всего к оплате: {total_amount:.2f} USDT</b>\n\n"
        f"Исполнитель получит: {amount + amount * (executor_comm / 100):.2f} USDT\n\n"
        f"Заявка создана. Ожидание исполнителя...",
        reply_markup=back(), parse_mode="HTML")

@dp.callback_query(F.data == "orders")
async def orders(c: CallbackQuery):
    rows = await get_orders(c.from_user.id)
    text = "📋 <b>Мои заявки</b>\n\n"
    if not rows:
        text += "Заявок пока нет."
    else:
        text += "\n".join(
            f"#{x[0]} — {x[1]}\nСумма: {x[2]:.2f} USDT | Итого: {x[3]:.2f} USDT\nСтатус: {ORDER_STATUS_LABELS.get(x[4], x[4])}\n"
            for x in rows)
    await c.message.edit_text(text, reply_markup=back(), parse_mode="HTML")
    await c.answer()

@dp.callback_query(F.data == "executor")
async def executor(c: CallbackQuery):
    await c.message.edit_text(
        "🧑‍💼 <b>Исполнитель</b>\n\nРегистрация исполнителей будет добавлена следующим этапом.",
        reply_markup=back(), parse_mode="HTML")
    await c.answer()

@dp.callback_query(F.data == "support")
async def support(c: CallbackQuery):
    await c.message.edit_text(
        "🆘 <b>Поддержка</b>\n\nСвязь с поддержкой будет добавлена следующим этапом.",
        reply_markup=back(), parse_mode="HTML")
    await c.answer()

@dp.callback_query(F.data == "back")
async def go_back(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await c.message.edit_text(
        "🏠 <b>TornadoPay</b>\n\nВыберите раздел:",
        reply_markup=menu(c.from_user.id), parse_mode="HTML")
    await c.answer()

async def main():
    await init_db()
    bot = Bot(TOKEN)
    try:
        await dp.start_polling(bot)
    finally:
        await close_db()
