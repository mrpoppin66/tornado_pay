import os
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv
from .db import (
    init_db, close_db, ensure_user, get_user, get_services, get_service, create_order, 
    get_orders, ORDER_STATUS_LABELS, get_exchange_rate, start_exchange_rate_updater,
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
    rate = get_exchange_rate()
    await m.answer(
        f"👋 Добро пожаловать в <b>TornadoPay</b>!\n\n"
        f"Маркетплейс услуг с оплатой в криптовалюте.\n"
        f"Выберите услугу и укажите сумму в рублях.\n\n"
        f"📊 Текущий курс: 1 USDT = {rate:.2f} RUB",
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
    rate = get_exchange_rate()
    min_rub_text = []
    for x in rows:
        min_rub = float(x[3]) * rate
        min_rub_text.append(f"{x[1]} (мин. {x[3]:.2f} USDT / ~{min_rub:.0f} RUB)")
    
    kb = [[InlineKeyboardButton(text=text, callback_data=f"svc:{rows[i][0]}")] for i, text in enumerate(min_rub_text)]
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
    
    rate = get_exchange_rate()
    await state.update_data(service_id=sid, service_name=service[1], 
                           min_amount_usdt=float(service[3]), 
                           owner_comm=float(service[4]),
                           executor_comm=float(service[5]),
                           exchange_rate=rate)
    await state.set_state(UserStates.waiting_order_amount)
    
    total_comm = float(service[4]) + float(service[5])
    min_rub = float(service[3]) * rate
    
    await c.message.edit_text(
        f"🛒 <b>{service[1]}</b>\n\n"
        f"{service[2]}\n\n"
        f"Минимальная сумма: {service[3]:.2f} USDT (~{min_rub:.0f} RUB)\n"
        f"Комиссия: {total_comm:.1f}%\n"
        f"Текущий курс: 1 USDT = {rate:.2f} RUB\n\n"
        f"Пришлите сумму в <b>рублях</b> (например 300 или 150.50):",
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
        amount_rub = float(m.text.strip().replace(",", "."))
    except ValueError:
        await m.answer("Неверный формат. Пришлите сумму числом (например 300 или 150.50).")
        return
    
    data = await state.get_data()
    rate = data["exchange_rate"]
    min_amount_usdt = float(data["min_amount_usdt"])
    min_rub = min_amount_usdt * rate
    
    if amount_rub < min_rub:
        await m.answer(f"❌ Минимальная сумма: {min_rub:.2f} RUB ({min_amount_usdt:.2f} USDT)")
        return
    
    # Создаём заявку
    oid = await create_order(m.from_user.id, data["service_id"], amount_rub)
    if not oid:
        await m.answer("❌ Ошибка при создании заявки. Попробуйте ещё раз.")
        await state.clear()
        return
    
    owner_comm = float(data["owner_comm"])
    executor_comm = float(data["executor_comm"])
    total_comm = owner_comm + executor_comm
    
    # Конвертируем в USDT
    user_amount_usdt = amount_rub / rate
    commission_usdt = user_amount_usdt * (total_comm / 100)
    total_amount_usdt = user_amount_usdt + commission_usdt
    executor_amount_usdt = user_amount_usdt + (user_amount_usdt * (executor_comm / 100))
    
    await state.clear()
    await m.answer(
        f"🧾 <b>Заявка #{oid}</b>\n\n"
        f"Услуга: {data['service_name']}\n"
        f"Сумма в рублях: {amount_rub:.2f} RUB\n\n"
        f"<b>Для пользователя:</b>\n"
        f"К оплате: {user_amount_usdt:.4f} USDT\n"
        f"Комиссия: {commission_usdt:.4f} USDT\n"
        f"<b>Всего: {total_amount_usdt:.4f} USDT</b>\n\n"
        f"<b>Для исполнителя:</b>\n"
        f"К выполнению: {amount_rub:.2f} RUB\n"
        f"Получит: {executor_amount_usdt:.4f} USDT\n\n"
        f"Курс фиксирован. Ожидание исполнителя...",
        reply_markup=back(), parse_mode="HTML")

@dp.callback_query(F.data == "orders")
async def orders(c: CallbackQuery):
    rows = await get_orders(c.from_user.id)
    text = "📋 <b>Мои заявки</b>\n\n"
    if not rows:
        text += "Заявок пока нет."
    else:
        for x in rows:
            text += (f"#{x[0]} — {x[1]}\n"
                    f"Сумма: {x[2]:.2f} RUB → {x[3]:.4f} USDT\n"
                    f"Итого: {x[4]:.4f} USDT | {ORDER_STATUS_LABELS.get(x[5], x[5])}\n\n")
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
    rate = get_exchange_rate()
    await c.message.edit_text(
        f"🏠 <b>TornadoPay</b>\n\n"
        f"Выберите раздел:\n\n"
        f"📊 Курс: 1 USDT = {rate:.2f} RUB",
        reply_markup=menu(c.from_user.id), parse_mode="HTML")
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
