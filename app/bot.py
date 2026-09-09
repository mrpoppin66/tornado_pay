import os
from html import escape
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv
from .db import (
<<<<<<< HEAD
    init_db, close_db, ensure_user, get_user, get_services, get_service, create_order,
    get_orders, ORDER_STATUS_LABELS, get_exchange_rate, start_exchange_rate_updater,
    get_active_executor_application, get_latest_executor_application,
    create_executor_application, answer_executor_application,
    EXECUTOR_APPLICATION_STATUSES, get_free_orders, claim_order, complete_executor_order,
    confirm_order_by_client, dispute_order_by_client,
=======
    init_db, close_db, ensure_user, get_user, get_services, get_service, create_order, 
    get_orders, ORDER_STATUS_LABELS, get_exchange_rate, start_exchange_rate_updater,
>>>>>>> 2d9d72719a02f678dcd9f49b9dd0b8e868a18a43
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
<<<<<<< HEAD
    executor_experience = State()
    executor_services = State()
    executor_comment = State()
    executor_answer = State()
=======
>>>>>>> 2d9d72719a02f678dcd9f49b9dd0b8e868a18a43

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
<<<<<<< HEAD

=======
    
>>>>>>> 2d9d72719a02f678dcd9f49b9dd0b8e868a18a43
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
<<<<<<< HEAD

    rate = get_exchange_rate()
    await state.update_data(service_id=sid, service_name=service[1],
                           min_amount_usdt=float(service[3]),
                           owner_comm=float(service[4]),
                           executor_comm=float(service[5]))
    await state.set_state(UserStates.waiting_order_amount)

    total_comm = float(service[4]) + float(service[5])
    min_rub = float(service[3]) * rate

=======
    
    rate = get_exchange_rate()
    await state.update_data(service_id=sid, service_name=service[1], 
                           min_amount_usdt=float(service[3]), 
                           owner_comm=float(service[4]),
                           executor_comm=float(service[5]),
                           exchange_rate=rate)
    await state.set_state(UserStates.waiting_order_amount)
    
    total_comm = float(service[4]) + float(service[5])
    min_rub = float(service[3]) * rate
    
>>>>>>> 2d9d72719a02f678dcd9f49b9dd0b8e868a18a43
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
<<<<<<< HEAD

=======
    
>>>>>>> 2d9d72719a02f678dcd9f49b9dd0b8e868a18a43
    try:
        amount_rub = float(m.text.strip().replace(",", "."))
    except ValueError:
        await m.answer("Неверный формат. Пришлите сумму числом (например 300 или 150.50).")
        return
<<<<<<< HEAD

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
        else:
            await m.answer("❌ Не удалось создать заявку. Попробуйте ещё раз.", reply_markup=back())
        return

    owner_comm = float(data["owner_comm"])
    executor_comm = float(data["executor_comm"])
    total_comm = owner_comm + executor_comm

    # Конвертируем в USDT по тому же зафиксированному курсу
=======
    
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
>>>>>>> 2d9d72719a02f678dcd9f49b9dd0b8e868a18a43
    user_amount_usdt = amount_rub / rate
    commission_usdt = user_amount_usdt * (total_comm / 100)
    total_amount_usdt = user_amount_usdt + commission_usdt
    executor_amount_usdt = user_amount_usdt + (user_amount_usdt * (executor_comm / 100))
<<<<<<< HEAD

=======
    
>>>>>>> 2d9d72719a02f678dcd9f49b9dd0b8e868a18a43
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
<<<<<<< HEAD
        f"Курс {rate:.2f} RUB/USDT зафиксирован. Ожидание исполнителя...",
=======
        f"Курс фиксирован. Ожидание исполнителя...",
>>>>>>> 2d9d72719a02f678dcd9f49b9dd0b8e868a18a43
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

def executor_application_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Подать заявку", callback_data="exec:apply")],
        [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="back")],
    ])


def executor_cabinet_kb(available=False):
    rows = [[InlineKeyboardButton(text=("🔴 Стать недоступным" if available else "🟢 Стать доступным"),
                                  callback_data=("exec:availability:0" if available else "exec:availability:1"))]]
    if available:
        rows.append([InlineKeyboardButton(text="🆕 Свободные заявки", callback_data="exec:free")])
    rows.append([InlineKeyboardButton(text="📋 Мои заявки", callback_data="exec:myorders")])
    rows.append([InlineKeyboardButton(text="⬅️ Главное меню", callback_data="back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@dp.callback_query(F.data == "executor")
async def executor(c: CallbackQuery, state: FSMContext):
    await state.clear()
    u = await get_user(c.from_user.id)
    app = await get_latest_executor_application(c.from_user.id)
    if u and u[3] == "executor":
        if u[7]:
            await c.message.edit_text("🚫 <b>Доступ исполнителя заблокирован администрацией.</b>\n\nОбратитесь в поддержку.", reply_markup=back(), parse_mode="HTML")
        else:
            status = "🟢 Доступен" if u[6] else "🔴 Не доступен"
            stats = await __import__(".db", fromlist=["get_executor_stats"]).get_executor_stats(c.from_user.id)
            await c.message.edit_text(
                f"🧑‍💼 <b>Кабинет исполнителя</b>\n\nСтатус: {status}\n"
                f"Выполнено: {stats['completed']}\n"
                f"Рейтинг: {stats['avg_rating']:.2f} ⭐ ({stats['total_ratings']})",
                reply_markup=executor_cabinet_kb(bool(u[6])), parse_mode="HTML")
    elif app and app[5] in ("pending", "question"):
        label = EXECUTOR_APPLICATION_STATUSES[app[5]]
        text = f"🧑‍💼 <b>Заявка исполнителя</b>\n\nСтатус: <b>{label}</b>"
        if app[5] == "question":
            text += "\n\n💬 Администрация ожидает вашего ответа."
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💬 Ответить", callback_data=f"exec:answer:{app[0]}")], [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="back")]])
        else:
            text += "\n\nМы уведомим вас после принятия решения."
            kb = back()
        await c.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    elif app and app[5] == "rejected":
        reason = app[8] or "не указана"
        await c.message.edit_text(
            f"❌ <b>Ваша заявка отклонена.</b>\n\nПричина: {escape(reason)}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📝 Подать новую заявку", callback_data="exec:apply")], [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="back")]]), parse_mode="HTML")
    else:
        await c.message.edit_text(
            "🧑‍💼 <b>Стать исполнителем</b>\n\n"
            "Для получения доступа к заявкам необходимо подать заявку.\n\n"
            "После заполнения она будет рассмотрена администрацией Tornado Pay.",
            reply_markup=executor_application_kb(), parse_mode="HTML")
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
    if not u or u[3] != "executor" or u[7] or not u[6]:
        await c.answer("Сначала включите доступность.", show_alert=True)
        return
    rows = await get_free_orders()
    kb = []
    for x in rows:
        kb.append([InlineKeyboardButton(
            text=f"#{x[0]} • {x[1]} • {float(x[2]):.2f} RUB",
            callback_data=f"exec:order:{x[0]}" )])
    kb.append([InlineKeyboardButton(text="⬅️ Кабинет", callback_data="executor")])
    text = "🆕 <b>Свободные заявки</b>\n\n"
    text += "Нет свободных заявок." if not rows else "Выберите заявку для просмотра:"
    await c.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
    await c.answer()

@dp.callback_query(F.data.startswith("exec:order:"))
async def executor_order_detail(c: CallbackQuery):
    order_id = int(c.data.split(":")[2])
    u = await get_user(c.from_user.id)
    if not u or u[3] != "executor" or u[7] or not u[6]:
        await c.answer("Вы сейчас недоступны для новых заявок.", show_alert=True)
        return
    from .db import get_order
    o = await get_order(order_id)
    if not o or o[9] != "new" or o[10] is not None:
        await c.answer("Заявка уже занята или недоступна.", show_alert=True)
        return
    text = (f"🧾 <b>Заявка #{o[0]}</b>\n\n"
            f"Услуга: <b>{escape(o[3])}</b>\n"
            f"Сумма: {float(o[4]):.2f} RUB\n"
            f"Клиент оплачивает: {float(o[6]):.4f} USDT\n"
            f"Ваш заработок: <b>{(float(o[5]) + float(o[8])):.4f} USDT</b>\n\n"
            f"Статус: 🆕 Свободна")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Взять в работу", callback_data=f"exec:claim:{order_id}")],
        [InlineKeyboardButton(text="⬅️ К свободным заявкам", callback_data="exec:free")],
    ])
    await c.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await c.answer()

@dp.callback_query(F.data.startswith("exec:claim:"))
async def executor_claim(c: CallbackQuery):
    order_id = int(c.data.split(":")[2])
    client_id, result = await claim_order(order_id, c.from_user.id)
    if result != 'ok':
        messages = {'already_taken': 'Заявку уже взял другой исполнитель.', 'unavailable': 'Вы недоступны для новых заявок.', 'not_found': 'Заявка не найдена.', 'own_order': 'Нельзя взять собственную заявку.'}
        await c.answer(messages.get(result, 'Не удалось взять заявку.'), show_alert=True)
        return
    from .db import get_order
    o = await get_order(order_id)
    try:
        await c.bot.send_message(client_id,
            f"🔧 <b>Исполнитель найден!</b>\n\nЗаявка #{order_id} по услуге «{escape(o[3])}» принята исполнителем и взята в работу.\n\nСтатус: <b>В работе</b>",
            parse_mode="HTML")
    except Exception as e:
        print(f"[Executor claim notify] {e}")
    await c.message.edit_text(
        f"🔧 <b>Заявка #{order_id} взята в работу</b>\n\nУслуга: {escape(o[3])}\nСумма: {float(o[4]):.2f} RUB\nВаш заработок: <b>{float(o[8]):.4f} USDT</b>\n\nСвяжитесь с клиентом и выполните заявку.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Отметить выполненной", callback_data=f"exec:done:{order_id}")],
            [InlineKeyboardButton(text="🆕 Свободные заявки", callback_data="exec:free")],
            [InlineKeyboardButton(text="⬅️ Кабинет", callback_data="executor")],
        ]), parse_mode="HTML")
    await c.answer("Заявка взята в работу")

@dp.callback_query(F.data.startswith("exec:done:"))
async def executor_done(c: CallbackQuery):
    order_id = int(c.data.split(":")[2])
    client_id = await complete_executor_order(order_id, c.from_user.id)
    if not client_id:
        await c.answer("Заявка уже завершена или вам не принадлежит.", show_alert=True)
        return
    try:
        await c.bot.send_message(
            client_id,
            f"✅ <b>Заявка #{order_id} отмечена выполненной</b>\n\nПроверьте результат. Средства находятся в безопасном резерве и будут переданы исполнителю после вашего подтверждения.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Подтвердить выполнение", callback_data=f"order:confirm:{order_id}")],
                [InlineKeyboardButton(text="⚠️ Возникла проблема", callback_data=f"order:dispute:{order_id}")],
            ]),
            parse_mode="HTML")
    except Exception as e:
        print(f"[Executor done notify] {e}")
    await c.message.edit_text(f"✅ <b>Заявка #{order_id} отмечена выполненной.</b>\n\nКлиент уведомлён.", reply_markup=back(), parse_mode="HTML")
    await c.answer("Готово")


@dp.callback_query(F.data.startswith("order:confirm:"))
async def client_confirm_order(c: CallbackQuery):
    order_id = int(c.data.split(":")[2])
    result = await confirm_order_by_client(order_id, c.from_user.id)
    if not result:
        await c.answer("Заявка уже подтверждена, находится в споре или недоступна.", show_alert=True)
        return
    executor_id, payout = result
    try:
        await c.bot.send_message(executor_id, f"🎉 <b>Заявка #{order_id} подтверждена клиентом!</b>\n\nВам начислено <b>{payout:.4f} USDT</b>.", parse_mode="HTML")
    except Exception as e:
        print(f"[Confirm notify] {e}")
    await c.message.edit_text(f"✅ <b>Заявка #{order_id} завершена</b>\n\nОплата передана исполнителю: <b>{payout:.4f} USDT</b>.\nСпасибо за использование TornadoPay!", reply_markup=back(), parse_mode="HTML")
    await c.answer("Выполнение подтверждено")

@dp.callback_query(F.data.startswith("order:dispute:"))
async def client_dispute_order(c: CallbackQuery):
    order_id = int(c.data.split(":")[2])
    executor_id = await dispute_order_by_client(order_id, c.from_user.id)
    if executor_id is None:
        await c.answer("Заявка уже обработана или недоступна.", show_alert=True)
        return
    await c.message.edit_text(f"⚠️ <b>Заявка #{order_id} передана в спор</b>\n\nСредства остаются в резерве. Администрация TornadoPay рассмотрит ситуацию и примет решение.", reply_markup=back(), parse_mode="HTML")
    for admin_id in ADMIN_IDS:
        try:
            await c.bot.send_message(admin_id, f"⚠️ <b>Открыт спор по заявке #{order_id}</b>\n\nКлиент: <code>{c.from_user.id}</code>\nИсполнитель: <code>{executor_id}</code>", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="👷 В пользу исполнителя", callback_data=f"adm:settle:{order_id}:executor")],
                [InlineKeyboardButton(text="👤 Вернуть клиенту", callback_data=f"adm:settle:{order_id}:client")],
            ]), parse_mode="HTML")
        except Exception as e:
            print(f"[Dispute admin notify] {e}")
    await c.answer("Спор открыт")

@dp.callback_query(F.data == "exec:myorders")
async def executor_my_orders(c: CallbackQuery):
    u = await get_user(c.from_user.id)
    if not u or u[3] != "executor" or u[7]:
        await c.answer("Доступ запрещён.", show_alert=True)
        return
    from .db import get_executor_orders
    rows = await get_executor_orders(c.from_user.id)
    text = "📋 <b>Мои заявки исполнителя</b>\n\n"
    if not rows:
        text += "Заявок пока нет."
    else:
        for x in rows:
            text += f"#{x[0]} — {escape(x[1])}\n{float(x[2]):.2f} RUB → {float(x[3]):.4f} USDT | {ORDER_STATUS_LABELS.get(x[4], x[4])}\n\n"
    await c.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Кабинет", callback_data="executor")]]), parse_mode="HTML")
    await c.answer()

@dp.callback_query(F.data.startswith("exec:availability:"))
async def executor_availability(c: CallbackQuery):
    value = c.data.split(":")[2] == "1"
    u = await get_user(c.from_user.id)
    if not u or u[3] != "executor" or u[7]:
        await c.answer("Доступ исполнителя заблокирован.", show_alert=True)
        return
    from .db import set_executor_available
    await set_executor_available(c.from_user.id, value)
    await c.message.edit_text(
        f"🧑‍💼 <b>Кабинет исполнителя</b>\n\nСтатус: {'🟢 Доступен' if value else '🔴 Не доступен'}",
        reply_markup=executor_cabinet_kb(value), parse_mode="HTML")
    await c.answer("Статус обновлён")

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
<<<<<<< HEAD

    # Запускаем фоновое обновление курса
    import asyncio
    asyncio.create_task(start_exchange_rate_updater())

=======
    
    # Запускаем фоновое обновление курса
    import asyncio
    asyncio.create_task(start_exchange_rate_updater())
    
>>>>>>> 2d9d72719a02f678dcd9f49b9dd0b8e868a18a43
    bot = Bot(TOKEN)
    try:
        await dp.start_polling(bot)
    finally:
        await close_db()
