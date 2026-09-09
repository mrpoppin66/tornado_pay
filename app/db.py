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
<<<<<<< HEAD

async def _add_column_if_missing(conn, table: str, column: str, ddl: str):
    """Безопасная миграция: добавить колонку, если её ещё нет."""
    exists = await conn.fetchval(
        """SELECT EXISTS(
               SELECT 1 FROM information_schema.columns
               WHERE table_name = $1 AND column_name = $2)""",
        table, column,
    )
    if not exists:
        await conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
        print(f"[Migration] {table}.{column} добавлена")
=======
>>>>>>> 2d9d72719a02f678dcd9f49b9dd0b8e868a18a43

async def init_db():
    global pool
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=10)
    async with pool.acquire() as conn:
<<<<<<< HEAD
        # ВАЖНО: никаких DROP TABLE — данные должны переживать редеплой.
=======
        # Удаляем старые таблицы (миграция)
        await conn.execute("DROP TABLE IF EXISTS ratings CASCADE")
        await conn.execute("DROP TABLE IF EXISTS orders CASCADE")
        await conn.execute("DROP TABLE IF EXISTS services CASCADE")
        await conn.execute("DROP TABLE IF EXISTS users CASCADE")
        
        # Создаём таблицы с новой схемой
>>>>>>> 2d9d72719a02f678dcd9f49b9dd0b8e868a18a43
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS users(
            user_id BIGINT PRIMARY KEY,
            username TEXT,
            balance NUMERIC(18,4) NOT NULL DEFAULT 0,
            role TEXT NOT NULL DEFAULT 'client',
            executor_name TEXT,
            executor_description TEXT,
            executor_city TEXT,
            executor_available BOOLEAN NOT NULL DEFAULT FALSE,
<<<<<<< HEAD
            executor_blocked BOOLEAN NOT NULL DEFAULT FALSE,
=======
>>>>>>> 2d9d72719a02f678dcd9f49b9dd0b8e868a18a43
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
            executor_id BIGINT REFERENCES users(user_id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
<<<<<<< HEAD
            completed_at TIMESTAMPTZ,
            confirmed_at TIMESTAMPTZ,
            disputed_at TIMESTAMPTZ,
            settled_at TIMESTAMPTZ,
            escrow_amount_usdt NUMERIC(18,4) NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS executor_applications(
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES users(user_id),
            experience TEXT NOT NULL DEFAULT '',
            services TEXT NOT NULL DEFAULT '',
            comment TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'draft',
            admin_question TEXT,
            executor_answer TEXT,
            rejection_reason TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE TABLE IF NOT EXISTS transactions(
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES users(user_id),
            order_id INTEGER REFERENCES orders(id),
            amount NUMERIC(18,4) NOT NULL,
            type TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
=======
            completed_at TIMESTAMPTZ
>>>>>>> 2d9d72719a02f678dcd9f49b9dd0b8e868a18a43
        );
        CREATE TABLE IF NOT EXISTS ratings(
            id SERIAL PRIMARY KEY,
            order_id INTEGER NOT NULL REFERENCES orders(id),
            from_user_id BIGINT NOT NULL REFERENCES users(user_id),
            to_user_id BIGINT NOT NULL REFERENCES users(user_id),
            stars INTEGER NOT NULL CHECK (stars >= 1 AND stars <= 5),
            comment TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """)
<<<<<<< HEAD

        # Миграции для старых баз: добавляем колонки, которых может не хватать
        await _add_column_if_missing(conn, "users", "role", "TEXT NOT NULL DEFAULT 'client'")
        await _add_column_if_missing(conn, "users", "executor_name", "TEXT")
        await _add_column_if_missing(conn, "users", "executor_description", "TEXT")
        await _add_column_if_missing(conn, "users", "executor_city", "TEXT")
        await _add_column_if_missing(conn, "users", "executor_available", "BOOLEAN NOT NULL DEFAULT FALSE")
        await _add_column_if_missing(conn, "users", "executor_blocked", "BOOLEAN NOT NULL DEFAULT FALSE")
        await _add_column_if_missing(conn, "users", "created_at", "TIMESTAMPTZ NOT NULL DEFAULT now()")
        await conn.execute("ALTER TABLE users ALTER COLUMN balance TYPE NUMERIC(18,4) USING balance::numeric(18,4)")
        await _add_column_if_missing(conn, "services", "active", "BOOLEAN NOT NULL DEFAULT TRUE")
        await _add_column_if_missing(conn, "services", "created_at", "TIMESTAMPTZ NOT NULL DEFAULT now()")
        await _add_column_if_missing(conn, "orders", "exchange_rate", "NUMERIC(14,4) NOT NULL DEFAULT 100")
        await _add_column_if_missing(conn, "orders", "executor_id", "BIGINT")
        await _add_column_if_missing(conn, "orders", "completed_at", "TIMESTAMPTZ")
        await _add_column_if_missing(conn, "orders", "confirmed_at", "TIMESTAMPTZ")
        await _add_column_if_missing(conn, "orders", "disputed_at", "TIMESTAMPTZ")
        await _add_column_if_missing(conn, "orders", "settled_at", "TIMESTAMPTZ")
        await _add_column_if_missing(conn, "orders", "escrow_amount_usdt", "NUMERIC(18,4) NOT NULL DEFAULT 0")

=======
        
>>>>>>> 2d9d72719a02f678dcd9f49b9dd0b8e868a18a43
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
            "SELECT user_id, username, balance, role, executor_name, executor_description, executor_city, executor_available FROM users WHERE user_id=$1",
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

<<<<<<< HEAD
async def create_order(user_id, service_id, amount_rub, rate=None):
    """Create an order and reserve the full client payment in escrow."""
    async with pool.acquire() as conn:
        async with conn.transaction():
            service = await conn.fetchrow(
                "SELECT owner_commission, executor_commission FROM services WHERE id=$1 AND active=TRUE FOR SHARE", service_id
            )
            if not service:
                return None, "service_not_found"
            owner_comm = float(service[0]); executor_comm = float(service[1])
            rate = float(rate or get_exchange_rate()); amount_rub = float(amount_rub)
            user_amount_usdt = amount_rub / rate
            total_comm = owner_comm + executor_comm
            commission_usdt = user_amount_usdt * total_comm / 100
            total_amount_usdt = user_amount_usdt + commission_usdt
            owner_amount = user_amount_usdt * owner_comm / 100
            executor_amount = user_amount_usdt * executor_comm / 100
            balance = await conn.fetchval("SELECT balance FROM users WHERE user_id=$1 FOR UPDATE", user_id)
            if balance is None:
                return None, "user_not_found"
            if float(balance) + 1e-9 < total_amount_usdt:
                return None, "insufficient_balance"
            order_id = await conn.fetchval(
                """INSERT INTO orders(user_id, service_id, amount_rub, exchange_rate, user_amount_usdt,
                    total_amount_usdt, owner_commission_amount, executor_commission_amount, escrow_amount_usdt)
                   VALUES($1,$2,$3,$4,$5,$6,$7,$8,$6) RETURNING id""",
                user_id, service_id, amount_rub, rate, user_amount_usdt, total_amount_usdt, owner_amount, executor_amount)
            await conn.execute("UPDATE users SET balance=balance-$1 WHERE user_id=$2", total_amount_usdt, user_id)
            await conn.execute("INSERT INTO transactions(user_id,order_id,amount,type,description) VALUES($1,$2,$3,'escrow_hold',$4)", user_id, order_id, -total_amount_usdt, f"Резерв по заявке #{order_id}")
            return order_id, "ok"
=======
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
>>>>>>> 2d9d72719a02f678dcd9f49b9dd0b8e868a18a43

async def get_orders(user_id):
    async with pool.acquire() as conn:
        return await conn.fetch(
            """SELECT o.id, s.name, o.amount_rub, o.user_amount_usdt, o.total_amount_usdt, o.status, o.executor_id, o.created_at
               FROM orders o JOIN services s ON s.id = o.service_id
               WHERE o.user_id = $1 ORDER BY o.id DESC LIMIT 20""",
            user_id,
        )

# ---------- Исполнители ----------

async def register_executor(user_id, name, description, city):
    """Зарегистрировать пользователя как исполнителя"""
    async with pool.acquire() as conn:
        await conn.execute(
<<<<<<< HEAD
            """UPDATE users SET role=$1, executor_name=$2, executor_description=$3,
               executor_city=$4, executor_available=$5
=======
            """UPDATE users SET role=$1, executor_name=$2, executor_description=$3, 
               executor_city=$4, executor_available=$5 
>>>>>>> 2d9d72719a02f678dcd9f49b9dd0b8e868a18a43
               WHERE user_id=$6""",
            "executor", name, description, city, False, user_id
        )

async def set_executor_available(user_id, available):
    """Включить/выключить доступность исполнителя"""
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET executor_available=$1 WHERE user_id=$2",
            available, user_id
        )

async def get_available_executors():
<<<<<<< HEAD
    """Получить всех доступных исполнителей"""
=======
    """Получить в��ех доступных исполнителей"""
>>>>>>> 2d9d72719a02f678dcd9f49b9dd0b8e868a18a43
    async with pool.acquire() as conn:
        return await conn.fetch(
            """SELECT user_id, username, executor_name, executor_description, executor_city
               FROM users WHERE role='executor' AND executor_available=TRUE ORDER BY user_id"""
        )

async def get_executor_stats(executor_id):
    """Получить статистику исполнителя: рейтинг, кол-во выполненных"""
    async with pool.acquire() as conn:
        completed = await conn.fetchval(
            "SELECT COUNT(*) FROM orders WHERE executor_id=$1 AND status='done'",
            executor_id
        )
        rating_data = await conn.fetchrow(
            """SELECT AVG(stars) as avg_rating, COUNT(*) as total_ratings
               FROM ratings WHERE to_user_id=$1""",
            executor_id
        )
        avg_rating = float(rating_data["avg_rating"]) if rating_data["avg_rating"] else 0
        total_ratings = rating_data["total_ratings"] or 0
<<<<<<< HEAD

=======
        
>>>>>>> 2d9d72719a02f678dcd9f49b9dd0b8e868a18a43
        return {
            "completed": completed,
            "avg_rating": avg_rating,
            "total_ratings": total_ratings
        }

<<<<<<< HEAD
async def get_free_orders(limit=20):
    """Получить свободные заявки, доступные исполнителям."""
    async with pool.acquire() as conn:
        return await conn.fetch(
            """SELECT o.id, s.name, o.amount_rub, o.user_amount_usdt,
                      o.executor_commission_amount, o.created_at
               FROM orders o
               JOIN services s ON s.id = o.service_id
               WHERE o.status='new' AND o.executor_id IS NULL
               ORDER BY o.id ASC LIMIT $1""", limit
        )

async def claim_order(order_id, executor_id):
    """Атомарно взять свободную заявку в работу."""
    async with pool.acquire() as conn:
        async with conn.transaction():
            executor = await conn.fetchrow(
                "SELECT role, executor_available, executor_blocked FROM users WHERE user_id=$1 FOR UPDATE",
                executor_id,
            )
            if not executor or executor[0] != 'executor' or not executor[1] or executor[2]:
                return None, 'unavailable'
            order = await conn.fetchrow(
                "SELECT id, user_id, status, executor_id FROM orders WHERE id=$1 FOR UPDATE",
                order_id,
            )
            if not order:
                return None, 'not_found'
            if order[2] != 'new' or order[3] is not None:
                return None, 'already_taken'
            if order[1] == executor_id:
                return None, 'own_order'
            await conn.execute(
                "UPDATE orders SET executor_id=$1, status='in_progress' WHERE id=$2 AND status='new' AND executor_id IS NULL",
                executor_id, order_id,
            )
            return order[1], 'ok'

async def complete_executor_order(order_id, executor_id):
    """Mark an order as completed by executor; funds remain in escrow until client confirmation."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """UPDATE orders SET status='awaiting_confirmation', completed_at=now()
               WHERE id=$1 AND executor_id=$2 AND status='in_progress'
               RETURNING user_id""", order_id, executor_id)
        return row[0] if row else None

async def confirm_order_by_client(order_id, client_id):
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow("SELECT user_id, executor_id, user_amount_usdt, executor_commission_amount, escrow_amount_usdt, status FROM orders WHERE id=$1 FOR UPDATE", order_id)
            if not row or row[0] != client_id or row[5] != 'awaiting_confirmation' or not row[1] or float(row[4]) <= 0:
                return None
            payout = float(row[2]) + float(row[3])
            await conn.execute("UPDATE users SET balance=balance+$1 WHERE user_id=$2", payout, row[1])
            await conn.execute("UPDATE orders SET status='done', confirmed_at=now(), settled_at=now(), escrow_amount_usdt=0 WHERE id=$1", order_id)
            await conn.execute("INSERT INTO transactions(user_id,order_id,amount,type,description) VALUES($1,$2,$3,'executor_payout',$4)", row[1], order_id, payout, f"Выплата за заявку #{order_id}")
            return row[1], payout

async def dispute_order_by_client(order_id, client_id):
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """UPDATE orders SET status='disputed', disputed_at=now()
               WHERE id=$1 AND user_id=$2 AND status='awaiting_confirmation'
               RETURNING executor_id""", order_id, client_id)
        return row[0] if row else None

=======
>>>>>>> 2d9d72719a02f678dcd9f49b9dd0b8e868a18a43
async def get_executor_orders(executor_id, status=None):
    """Получить заявки исполнителя"""
    async with pool.acquire() as conn:
        if status:
            return await conn.fetch(
<<<<<<< HEAD
                """SELECT o.id, s.name, o.amount_rub, o.user_amount_usdt, o.status,
                          o.user_id, u.username, o.created_at
                   FROM orders o
=======
                """SELECT o.id, s.name, o.amount_rub, o.user_amount_usdt, o.status, 
                          o.user_id, u.username, o.created_at
                   FROM orders o 
>>>>>>> 2d9d72719a02f678dcd9f49b9dd0b8e868a18a43
                   JOIN services s ON s.id = o.service_id
                   JOIN users u ON u.user_id = o.user_id
                   WHERE o.executor_id=$1 AND o.status=$2
                   ORDER BY o.id DESC LIMIT 20""",
                executor_id, status
            )
        else:
            return await conn.fetch(
<<<<<<< HEAD
                """SELECT o.id, s.name, o.amount_rub, o.user_amount_usdt, o.status,
                          o.user_id, u.username, o.created_at
                   FROM orders o
=======
                """SELECT o.id, s.name, o.amount_rub, o.user_amount_usdt, o.status, 
                          o.user_id, u.username, o.created_at
                   FROM orders o 
>>>>>>> 2d9d72719a02f678dcd9f49b9dd0b8e868a18a43
                   JOIN services s ON s.id = o.service_id
                   JOIN users u ON u.user_id = o.user_id
                   WHERE o.executor_id=$1
                   ORDER BY o.id DESC LIMIT 20""",
                executor_id
            )

<<<<<<< HEAD
# ---------- Заявки исполнителей ----------

EXECUTOR_APPLICATION_STATUSES = {
    "draft": "📝 Черновик",
    "pending": "⏳ На рассмотрении",
    "question": "💬 Ожидается ответ",
    "approved": "✅ Одобрена",
    "rejected": "❌ Отклонена",
    "blocked": "🚫 Заблокирована",
}

async def get_active_executor_application(user_id):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            """SELECT id, user_id, experience, services, comment, status, admin_question,
                      executor_answer, rejection_reason, created_at, updated_at
               FROM executor_applications
               WHERE user_id=$1 AND status IN ('pending','question','approved','blocked')
               ORDER BY id DESC LIMIT 1""", user_id
        )

async def get_latest_executor_application(user_id):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            """SELECT id, user_id, experience, services, comment, status, admin_question,
                      executor_answer, rejection_reason, created_at, updated_at
               FROM executor_applications WHERE user_id=$1 ORDER BY id DESC LIMIT 1""", user_id
        )

async def create_executor_application(user_id, experience, services, comment):
    async with pool.acquire() as conn:
        existing = await conn.fetchval(
            "SELECT id FROM executor_applications WHERE user_id=$1 AND status IN ('pending','question','approved','blocked') ORDER BY id DESC LIMIT 1",
            user_id
        )
        if existing:
            return None
        return await conn.fetchval(
            """INSERT INTO executor_applications(user_id, experience, services, comment, status)
               VALUES($1,$2,$3,$4,'pending') RETURNING id""",
            user_id, experience, services, comment
        )

async def get_executor_application(application_id):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            """SELECT a.id, a.user_id, u.username, u.executor_name, a.experience, a.services,
                      a.comment, a.status, a.admin_question, a.executor_answer, a.rejection_reason,
                      a.created_at, a.updated_at
               FROM executor_applications a JOIN users u ON u.user_id=a.user_id
               WHERE a.id=$1""", application_id
        )

async def list_executor_applications(status=None, limit=30):
    async with pool.acquire() as conn:
        if status:
            return await conn.fetch(
                """SELECT a.id, a.user_id, u.username, a.status, a.created_at
                   FROM executor_applications a JOIN users u ON u.user_id=a.user_id
                   WHERE a.status=$1 ORDER BY a.id DESC LIMIT $2""", status, limit
            )
        return await conn.fetch(
            """SELECT a.id, a.user_id, u.username, a.status, a.created_at
               FROM executor_applications a JOIN users u ON u.user_id=a.user_id
               ORDER BY a.id DESC LIMIT $1""", limit
        )

async def set_executor_application_question(application_id, question):
    async with pool.acquire() as conn:
        await conn.execute(
            """UPDATE executor_applications SET status='question', admin_question=$1, updated_at=now()
               WHERE id=$2 AND status IN ('pending','question')""", question, application_id
        )

async def answer_executor_application(application_id, answer):
    async with pool.acquire() as conn:
        await conn.execute(
            """UPDATE executor_applications SET status='pending', executor_answer=$1, updated_at=now()
               WHERE id=$2 AND status='question'""", answer, application_id
        )

async def approve_executor_application(application_id):
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT user_id, status FROM executor_applications WHERE id=$1 FOR UPDATE", application_id
            )
            if not row or row[1] not in ('pending','question'):
                return None
            await conn.execute(
                """UPDATE executor_applications SET status='approved', rejection_reason=NULL, updated_at=now()
                   WHERE id=$1""", application_id
            )
            await conn.execute(
                """UPDATE users SET role='executor', executor_available=FALSE, executor_blocked=FALSE
                   WHERE user_id=$1""", row[0]
            )
            return row[0]

async def reject_executor_application(application_id, reason=''):
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT user_id, status FROM executor_applications WHERE id=$1 FOR UPDATE", application_id
            )
            if not row or row[1] not in ('pending','question'):
                return None
            await conn.execute(
                """UPDATE executor_applications SET status='rejected', rejection_reason=$1, updated_at=now()
                   WHERE id=$2""", reason, application_id
            )
            return row[0]

async def block_executor(user_id):
    async with pool.acquire() as conn:
        await conn.execute("UPDATE users SET executor_blocked=TRUE, executor_available=FALSE WHERE user_id=$1 AND role='executor'", user_id)
        await conn.execute("UPDATE executor_applications SET status='blocked', updated_at=now() WHERE user_id=$1 AND status='approved'", user_id)

async def unblock_executor(user_id):
    async with pool.acquire() as conn:
        await conn.execute("UPDATE users SET executor_blocked=FALSE, executor_available=FALSE WHERE user_id=$1 AND role='executor'", user_id)
        await conn.execute("UPDATE executor_applications SET status='approved', updated_at=now() WHERE user_id=$1 AND status='blocked'", user_id)

=======
>>>>>>> 2d9d72719a02f678dcd9f49b9dd0b8e868a18a43
# ---------- Рейтинги ----------

async def add_rating(order_id, from_user_id, to_user_id, stars, comment=""):
    """Добавить оценку"""
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO ratings(order_id, from_user_id, to_user_id, stars, comment)
               VALUES($1, $2, $3, $4, $5)""",
            order_id, from_user_id, to_user_id, stars, comment
        )

async def has_rating(order_id):
    """Проверить, есть ли уже оценка для этой заявки"""
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT COUNT(*) FROM ratings WHERE order_id=$1",
            order_id
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
<<<<<<< HEAD
            """INSERT INTO services(name, description, min_amount, owner_commission, executor_commission)
=======
            """INSERT INTO services(name, description, min_amount, owner_commission, executor_commission) 
>>>>>>> 2d9d72719a02f678dcd9f49b9dd0b8e868a18a43
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

ORDER_STATUSES = ("new", "in_progress", "awaiting_confirmation", "disputed", "done", "cancelled")
ORDER_STATUS_LABELS = {
    "new": "🆕 новая",
    "in_progress": "🔧 в работе",
    "awaiting_confirmation": "⏳ ожидает подтверждения",
    "disputed": "⚠️ спор",
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

async def settle_order_executor(order_id):
    """Release escrow to the assigned executor. Idempotent: only awaiting/disputed can settle."""
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT user_id, executor_id, user_amount_usdt, executor_commission_amount, escrow_amount_usdt, status FROM orders WHERE id=$1 FOR UPDATE", order_id)
            if not row or not row[1] or row[5] not in ('awaiting_confirmation','disputed'):
                return None
            payout = float(row[2]) + float(row[3])
            await conn.execute("UPDATE users SET balance=balance+$1 WHERE user_id=$2", payout, row[1])
            await conn.execute("UPDATE orders SET status='done', confirmed_at=COALESCE(confirmed_at, now()), settled_at=now(), escrow_amount_usdt=0 WHERE id=$1", order_id)
            await conn.execute("INSERT INTO transactions(user_id,order_id,amount,type,description) VALUES($1,$2,$3,'executor_payout',$4)", row[1], order_id, payout, f"Выплата за заявку #{order_id}")
            return row[1], payout

async def refund_order_client(order_id):
    """Return escrow to client when admin resolves a dispute in client's favor."""
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow("SELECT user_id, escrow_amount_usdt, status FROM orders WHERE id=$1 FOR UPDATE", order_id)
            if not row or row[2] != 'disputed' or float(row[1]) <= 0:
                return None
            refund = float(row[1])
            await conn.execute("UPDATE users SET balance=balance+$1 WHERE user_id=$2", refund, row[0])
            await conn.execute("UPDATE orders SET status='cancelled', settled_at=now(), escrow_amount_usdt=0 WHERE id=$1", order_id)
            await conn.execute("INSERT INTO transactions(user_id,order_id,amount,type,description) VALUES($1,$2,$3,'escrow_refund',$4)", row[0], order_id, refund, f"Возврат по спору #{order_id}")
            return row[0], refund

async def dispute_order_by_admin(order_id):
    async with pool.acquire() as conn:
        row = await conn.fetchrow("UPDATE orders SET status='disputed', disputed_at=now() WHERE id=$1 AND status='awaiting_confirmation' RETURNING executor_id", order_id)
        return row[0] if row else None

async def set_order_status(order_id, status):
    async with pool.acquire() as conn:
<<<<<<< HEAD
        async with conn.transaction():
            if status == "done":
                status = "awaiting_confirmation"
            if status == "cancelled":
                row = await conn.fetchrow("SELECT user_id, escrow_amount_usdt, status FROM orders WHERE id=$1 FOR UPDATE", order_id)
                if row and float(row[1]) > 0 and row[2] not in ('done','cancelled'):
                    refund = float(row[1])
                    await conn.execute("UPDATE users SET balance=balance+$1 WHERE user_id=$2", refund, row[0])
                    await conn.execute("INSERT INTO transactions(user_id,order_id,amount,type,description) VALUES($1,$2,$3,'escrow_refund',$4)", row[0], order_id, refund, f"Возврат по отменённой заявке #{order_id}")
                    await conn.execute("UPDATE orders SET escrow_amount_usdt=0, status='cancelled', settled_at=now() WHERE id=$1", order_id)
                    return
            if status == "awaiting_confirmation":
                await conn.execute("UPDATE orders SET status=$1, completed_at=COALESCE(completed_at, now()) WHERE id=$2", status, order_id)
            else:
                await conn.execute("UPDATE orders SET status=$1 WHERE id=$2", status, order_id)
=======
        if status == "done":
            await conn.execute(
                "UPDATE orders SET status=$1, completed_at=now() WHERE id=$2", status, order_id
            )
        else:
            await conn.execute(
                "UPDATE orders SET status=$1 WHERE id=$2", status, order_id
            )
>>>>>>> 2d9d72719a02f678dcd9f49b9dd0b8e868a18a43

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
                "SELECT user_id, username, balance, role, executor_blocked FROM users WHERE user_id=$1",
                int(query),
            )
        return await conn.fetchrow(
            "SELECT user_id, username, balance, role, executor_blocked FROM users WHERE username ILIKE $1",
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
        executors_count = await conn.fetchval(
            "SELECT COUNT(*) FROM users WHERE role='executor'"
        )
        return {
            "users": users_count,
            "orders": orders_count,
            "orders_by_status": {row["status"]: row["cnt"] for row in by_status},
            "active_services": services_count,
            "executors": executors_count,
        }
