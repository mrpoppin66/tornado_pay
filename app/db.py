import os
import asyncpg
import aiohttp
import asyncio
from datetime import datetime

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set")

pool: asyncpg.Pool | None = None
current_exchange_rate: float = 100.0  # RUB per 1 USDT (default)

async def fetch_exchange_rate():
    """Получить текущий курс USDT/RUB из CoinGecko"""
    global current_exchange_rate
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://api.coingecko.com/api/v3/simple/price?ids=tether&vs_currencies=rub"
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    rate = data.get("tether", {}).get("rub")
                    if rate:
                        current_exchange_rate = float(rate)
                        print(f"[Exchange Rate] Updated: 1 USDT = {current_exchange_rate:.2f} RUB")
    except Exception as e:
        print(f"[Exchange Rate Error] {e}")

async def start_exchange_rate_updater():
    """Фоновая задача: обновлять курс каждые 5 минут"""
    while True:
        try:
            await fetch_exchange_rate()
            await asyncio.sleep(300)  # 5 минут
        except Exception as e:
            print(f"[Exchange Rate Updater Error] {e}")
            await asyncio.sleep(300)

def get_exchange_rate():
    """Получить текущий курс"""
    return current_exchange_rate

async def init_db():
    global pool
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=10)
    async with pool.acquire() as conn:
        # Удаляем старые таблицы (миграция)
        await conn.execute("DROP TABLE IF EXISTS orders CASCADE")
        await conn.execute("DROP TABLE IF EXISTS services CASCADE")
        await conn.execute("DROP TABLE IF EXISTS users CASCADE")
        
        # Создаём таблицы с новой схемой
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS users(
            user_id BIGINT PRIMARY KEY,
            username TEXT,
            balance NUMERIC(14,2) NOT NULL DEFAULT 0,
            role TEXT NOT NULL DEFAULT 'client',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE TABLE IF NOT EXISTS services(
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            min_amount NUMERIC(14,2) NOT NULL DEFAULT 1.0,
            owner_commission NUMERIC(5,2) NOT NULL DEFAULT 0,
            executor_commission NUMERIC(5,2) NOT NULL DEFAULT 0,
            active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE TABLE IF NOT EXISTS orders(
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES users(user_id),
            service_id INTEGER NOT NULL REFERENCES services(id),
            amount_rub NUMERIC(14,2) NOT NULL,
            exchange_rate NUMERIC(14,4) NOT NULL,
            user_amount_usdt NUMERIC(14,4) NOT NULL,
            total_amount_usdt NUMERIC(14,4) NOT NULL,
            owner_commission_amount NUMERIC(14,4) NOT NULL,
            executor_commission_amount NUMERIC(14,4) NOT NULL,
            status TEXT NOT NULL DEFAULT 'new',
            executor_id BIGINT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """)
        
        count = await conn.fetchval("SELECT COUNT(*) FROM services")
        if count == 0:
            await conn.executemany(
                "INSERT INTO services(name, description, min_amount, owner_commission, executor_commission) VALUES($1, $2, $3, $4, $5)",
                [
                    ("📱 Пополнение мобильного", "Пополнение номера телефона", 10.0, 5.0, 5.0),
                    ("🧾 Оплата по QR", "Оплата по предоставленному QR-коду", 10.0, 5.0, 5.0),
                    ("💳 Перевод на карту", "Перевод средств на банковскую карту", 10.0, 5.0, 5.0),
                ],
            )
        
        # Первый fetch курса
        await fetch_exchange_rate()

async def close_db():
    if pool is not None:
        await pool.close()

async def ensure_user(user_id, username):
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO users(user_id, username) VALUES($1, $2)
               ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username""",
            user_id, username,
        )

async def get_user(user_id):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT user_id, username, balance, role FROM users WHERE user_id=$1",
            user_id,
        )

async def get_services():
    async with pool.acquire() as conn:
        return await conn.fetch(
            "SELECT id, name, description, min_amount, owner_commission, executor_commission FROM services WHERE active=TRUE ORDER BY id"
        )

async def get_service(service_id):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT id, name, description, min_amount, owner_commission, executor_commission, active FROM services WHERE id=$1",
            service_id,
        )

async def create_order(user_id, service_id, amount_rub):
    """
    Создаёт заявку с конвертацией рублей в USDT.
    amount_rub - сумма в рублях, которую вводит пользователь
    """
    async with pool.acquire() as conn:
        # Получаем параметры услуги
        service = await conn.fetchrow(
            "SELECT owner_commission, executor_commission FROM services WHERE id=$1",
            service_id
        )
        if not service:
            return None
        
        owner_comm = float(service[0])
        executor_comm = float(service[1])
        total_comm = owner_comm + executor_comm
        
        # Конвертируем рубли в USDT
        rate = get_exchange_rate()
        amount_rub = float(amount_rub)
        user_amount_usdt = amount_rub / rate
        
        # Расчёт комиссии в USDT
        commission_usdt = user_amount_usdt * (total_comm / 100)
        total_amount_usdt = user_amount_usdt + commission_usdt
        owner_commission_amount = user_amount_usdt * (owner_comm / 100)
        executor_commission_amount = user_amount_usdt * (executor_comm / 100)
        
        order_id = await conn.fetchval(
            """INSERT INTO orders(user_id, service_id, amount_rub, exchange_rate,
                                   user_amount_usdt, total_amount_usdt, 
                                   owner_commission_amount, executor_commission_amount) 
               VALUES($1, $2, $3, $4, $5, $6, $7, $8) RETURNING id""",
            user_id, service_id, amount_rub, rate,
            user_amount_usdt, total_amount_usdt,
            owner_commission_amount, executor_commission_amount
        )
        return order_id

async def get_orders(user_id):
    async with pool.acquire() as conn:
        return await conn.fetch(
            """SELECT o.id, s.name, o.amount_rub, o.user_amount_usdt, o.total_amount_usdt, o.status, o.executor_id, o.created_at
               FROM orders o JOIN services s ON s.id = o.service_id
               WHERE o.user_id = $1 ORDER BY o.id DESC LIMIT 20""",
            user_id,
        )

# ---------- Админ: услуги ----------

async def list_services_admin():
    async with pool.acquire() as conn:
        return await conn.fetch(
            "SELECT id, name, description, min_amount, owner_commission, executor_commission, active FROM services ORDER BY id"
        )

async def add_service(name, description, min_amount, owner_commission, executor_commission):
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """INSERT INTO services(name, description, min_amount, owner_commission, executor_commission) 
               VALUES($1, $2, $3, $4, $5) RETURNING id""",
            name, description, min_amount, owner_commission, executor_commission,
        )

async def toggle_service(service_id):
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "UPDATE services SET active = NOT active WHERE id=$1 RETURNING active",
            service_id,
        )

async def set_service_min_amount(service_id, min_amount):
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE services SET min_amount=$1 WHERE id=$2", min_amount, service_id
        )

async def set_service_owner_commission(service_id, commission):
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE services SET owner_commission=$1 WHERE id=$2", commission, service_id
        )

async def set_service_executor_commission(service_id, commission):
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE services SET executor_commission=$1 WHERE id=$2", commission, service_id
        )

# ---------- Админ: заявки ----------

ORDER_STATUSES = ("new", "in_progress", "done", "cancelled")
ORDER_STATUS_LABELS = {
    "new": "🆕 новая",
    "in_progress": "🔧 в работе",
    "done": "✅ выполнена",
    "cancelled": "❌ отменена",
}

async def get_orders_by_status(status, limit=15):
    async with pool.acquire() as conn:
        return await conn.fetch(
            """SELECT o.id, o.user_id, u.username, s.name, o.amount_rub, o.user_amount_usdt, o.total_amount_usdt,
                      o.owner_commission_amount, o.executor_commission_amount, o.status,
                      o.executor_id, o.created_at
               FROM orders o
               JOIN services s ON s.id = o.service_id
               JOIN users u ON u.user_id = o.user_id
               WHERE o.status = $1
               ORDER BY o.id DESC LIMIT $2""",
            status, limit,
        )

async def get_order(order_id):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            """SELECT o.id, o.user_id, u.username, s.name, o.amount_rub, o.user_amount_usdt, o.total_amount_usdt,
                      o.owner_commission_amount, o.executor_commission_amount, o.status,
                      o.executor_id, o.created_at
               FROM orders o
               JOIN services s ON s.id = o.service_id
               JOIN users u ON u.user_id = o.user_id
               WHERE o.id = $1""",
            order_id,
        )

async def set_order_status(order_id, status):
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE orders SET status=$1 WHERE id=$2", status, order_id
        )

async def assign_executor(order_id, executor_id):
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE orders SET executor_id=$1 WHERE id=$2", executor_id, order_id
        )

# ---------- Админ: пользователи ----------

async def find_user(query: str):
    query = query.strip().lstrip("@")
    async with pool.acquire() as conn:
        if query.isdigit():
            return await conn.fetchrow(
                "SELECT user_id, username, balance, role FROM users WHERE user_id=$1",
                int(query),
            )
        return await conn.fetchrow(
            "SELECT user_id, username, balance, role FROM users WHERE username ILIKE $1",
            query,
        )

async def adjust_balance(user_id, delta):
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "UPDATE users SET balance = balance + $1 WHERE user_id=$2 RETURNING balance",
            delta, user_id,
        )

# ---------- Админ: статистика ----------

async def get_stats():
    async with pool.acquire() as conn:
        users_count = await conn.fetchval("SELECT COUNT(*) FROM users")
        orders_count = await conn.fetchval("SELECT COUNT(*) FROM orders")
        by_status = await conn.fetch(
            "SELECT status, COUNT(*) AS cnt FROM orders GROUP BY status"
        )
        services_count = await conn.fetchval(
            "SELECT COUNT(*) FROM services WHERE active=TRUE"
        )
        return {
            "users": users_count,
            "orders": orders_count,
            "orders_by_status": {row["status"]: row["cnt"] for row in by_status},
            "active_services": services_count,
        }
