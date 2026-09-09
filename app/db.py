import os
import asyncpg

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set")

pool: asyncpg.Pool | None = None

async def init_db():
    global pool
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=10)
    async with pool.acquire() as conn:
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
            active BOOLEAN NOT NULL DEFAULT TRUE
        );
        CREATE TABLE IF NOT EXISTS orders(
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES users(user_id),
            service_id INTEGER NOT NULL REFERENCES services(id),
            amount NUMERIC(14,2) NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'new',
            executor_id BIGINT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """)
        # На случай если таблица services уже существовала без цены (миграция).
        await conn.execute(
            "ALTER TABLE services ADD COLUMN IF NOT EXISTS price NUMERIC(14,2) NOT NULL DEFAULT 0"
        )
        count = await conn.fetchval("SELECT COUNT(*) FROM services")
        if count == 0:
            await conn.executemany(
                "INSERT INTO services(name, description) VALUES($1, $2)",
                [
                    ("📱 Пополнение мобильного", "Пополнение номера телефона"),
                    ("🧾 Оплата по QR", "Оплата по предоставленному QR-коду"),
                    ("💳 Перевод на карту", "Перевод средств на банковскую карту"),
                ],
            )

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
            "SELECT id, name, description, price FROM services WHERE active=TRUE ORDER BY id"
        )

async def create_order(user_id, service_id, amount=0):
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "INSERT INTO orders(user_id, service_id, amount) VALUES($1, $2, $3) RETURNING id",
            user_id, service_id, amount,
        )

async def get_orders(user_id):
    async with pool.acquire() as conn:
        return await conn.fetch(
            """SELECT o.id, s.name, o.amount, o.status, o.executor_id, o.created_at
               FROM orders o JOIN services s ON s.id = o.service_id
               WHERE o.user_id = $1 ORDER BY o.id DESC LIMIT 20""",
            user_id,
        )

# ---------- Админ: услуги ----------

async def list_services_admin():
    async with pool.acquire() as conn:
        return await conn.fetch(
            "SELECT id, name, description, price, active FROM services ORDER BY id"
        )

async def get_service(service_id):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT id, name, description, price, active FROM services WHERE id=$1",
            service_id,
        )

async def add_service(name, description, price):
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "INSERT INTO services(name, description, price) VALUES($1, $2, $3) RETURNING id",
            name, description, price,
        )

async def toggle_service(service_id):
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "UPDATE services SET active = NOT active WHERE id=$1 RETURNING active",
            service_id,
        )

async def set_service_price(service_id, price):
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE services SET price=$1 WHERE id=$2", price, service_id
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
            """SELECT o.id, o.user_id, u.username, s.name, o.amount, o.status,
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
            """SELECT o.id, o.user_id, u.username, s.name, o.amount, o.status,
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
