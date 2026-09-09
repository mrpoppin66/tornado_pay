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
            "SELECT id, name, description FROM services WHERE active=TRUE ORDER BY id"
        )

async def create_order(user_id, service_id):
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "INSERT INTO orders(user_id, service_id) VALUES($1, $2) RETURNING id",
            user_id, service_id,
        )

async def get_orders(user_id):
    async with pool.acquire() as conn:
        return await conn.fetch(
            """SELECT o.id, s.name, o.amount, o.status, o.executor_id, o.created_at
               FROM orders o JOIN services s ON s.id = o.service_id
               WHERE o.user_id = $1 ORDER BY o.id DESC LIMIT 20""",
            user_id,
        )
