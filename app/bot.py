import os
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv
from .db import init_db, ensure_user, get_user, get_services, create_order, get_orders

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")

dp = Dispatcher()

def menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Баланс", callback_data="balance"),
         InlineKeyboardButton(text="🛒 Услуги", callback_data="services")],
        [InlineKeyboardButton(text="📋 Мои заявки", callback_data="orders"),
         InlineKeyboardButton(text="👤 Профиль", callback_data="profile")],
        [InlineKeyboardButton(text="🧑‍💼 Стать исполнителем", callback_data="executor"),
         InlineKeyboardButton(text="🆘 Поддержка", callback_data="support")],
    ])

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
        "Сейчас работает тестовый MVP — платежи пока не подключены.",
        reply_markup=menu(), parse_mode="HTML")

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
    kb = [[InlineKeyboardButton(text=x[1], callback_data=f"svc:{x[0]}")] for x in rows]
    kb.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back")])
    await c.message.edit_text(
        "🛒 <b>Услуги</b>\n\nВыберите услугу:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
    await c.answer()

@dp.callback_query(F.data.startswith("svc:"))
async def service(c: CallbackQuery):
    sid = int(c.data.split(":")[1])
    item = next((x for x in await get_services() if x[0] == sid), None)
    if not item:
        await c.answer("Услуга не найдена", show_alert=True)
        return
    oid = await create_order(c.from_user.id, sid)
    await c.message.edit_text(
        f"🧾 <b>Заявка #{oid}</b>\n\n"
        f"Услуга: {item[1]}\n{item[2]}\n\n"
        "Тестовая заявка создана. Реальная оплата и исполнители подключаются следующим этапом.",
        reply_markup=back(), parse_mode="HTML")
    await c.answer("Заявка создана")

@dp.callback_query(F.data == "orders")
async def orders(c: CallbackQuery):
    rows = await get_orders(c.from_user.id)
    text = "📋 <b>Мои заявки</b>\n\n"
    text += "Заявок пока нет." if not rows else "\n".join(
        f"#{x[0]} — {x[1]} — {x[3]}" for x in rows)
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
        "🆘 <b>Поддержка</b>\n\nПоддержка будет подключена вместе с админ-панелью.",
        reply_markup=back(), parse_mode="HTML")
    await c.answer()

@dp.callback_query(F.data == "back")
async def go_back(c: CallbackQuery):
    await c.message.edit_text(
        "🏠 <b>TornadoPay</b>\n\nВыберите раздел:",
        reply_markup=menu(), parse_mode="HTML")
    await c.answer()

async def main():
    await init_db()
    bot = Bot(TOKEN)
    await dp.start_polling(bot)
