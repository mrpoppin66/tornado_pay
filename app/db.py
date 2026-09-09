import os
import aiosqlite

DB = os.getenv("DATABASE_PATH", "/app/data/tornadopay.db")

async def init_db():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    async with aiosqlite.connect(DB) as db:
        await db.executescript("""
        CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            balance REAL NOT NULL DEFAULT 0,
            role TEXT NOT NULL DEFAULT 'client',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS services(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            active INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS orders(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            service_id INTEGER NOT NULL,
            amount REAL NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'new',
            executor_id INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """)
        cur = await db.execute("SELECT COUNT(*) FROM services")
        if (await cur.fetchone())[0] == 0:
            await db.executemany(
                "INSERT INTO services(name,description) VALUES(?,?)",
                [
                    ("📱 Пополнение мобильного", "Пополнение номера телефона"),
                    ("🧾 Оплата по QR", "Оплата по предоставленному QR-коду"),
                    ("💳 Перевод на карту", "Перевод средств на банковскую карту"),
                ],
            )
        await db.commit()

async def ensure_user(user_id, username):
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "INSERT INTO users(user_id,username) VALUES(?,?) "
            "ON CONFLICT(user_id) DO UPDATE SET username=excluded.username",
            (user_id, username),
        )
        await db.commit()

async def get_user(user_id):
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute(
            "SELECT user_id,username,balance,role FROM users WHERE user_id=?",
            (user_id,))
        return await cur.fetchone()

async def get_services():
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute(
            "SELECT id,name,description FROM services WHERE active=1 ORDER BY id")
        return await cur.fetchall()

async def create_order(user_id, service_id):
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute(
            "INSERT INTO orders(user_id,service_id) VALUES(?,?)",
            (user_id, service_id))
        await db.commit()
        return cur.lastrowid

async def get_orders(user_id):
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute(
            """SELECT o.id,s.name,o.amount,o.status,o.executor_id,o.created_at
               FROM orders o JOIN services s ON s.id=o.service_id
               WHERE o.user_id=? ORDER BY o.id DESC LIMIT 20""", (user_id,))
        return await cur.fetchall()
