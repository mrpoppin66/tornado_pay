import os
import asyncpg
import aiohttp
import asyncio
import json
import re
from datetime import datetime

try:
    from cryptography.fernet import Fernet, InvalidToken
except ImportError:  # dependency is declared in requirements.txt
    Fernet = None
    InvalidToken = Exception

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set")

pool: asyncpg.Pool | None = None
current_exchange_rate: float = 100.0  # RUB per 1 USDT — курс, который реально используется в боте (со скидкой)
raw_market_exchange_rate: float = 100.0  # RUB per 1 USDT — необработанный курс с CoinGecko, только для справки/логов

# Скидка к реальному рыночному курсу USDT/RUB, применяемая в боте.
# Пример: реальный курс 85 RUB/USDT, скидка 4.5% → в боте используется 85 * (1 - 0.045) = 81.175.
# Такой курс делает 1 USDT «дешевле» в рублях, поэтому за тот же рублёвый эквивалент
# клиент платит чуть больше USDT — в этом и есть маржа платформы.
EXCHANGE_RATE_MARKUP_PERCENT: float = float(os.getenv("EXCHANGE_RATE_MARKUP_PERCENT", "4.5"))

# Минимальная общая комиссия по любой услуге.
# Если процентная комиссия меньше этого значения, применяется минимум,
# а затем он делится между сервисом и исполнителем пропорционально
# комиссиям, заданным у конкретной услуги.
MIN_TOTAL_COMMISSION_RUB: float = 25.0

def calculate_order_commission(user_amount_usdt, rate, owner_commission, executor_commission):
    """Рассчитать общую комиссию и её доли.

    Возвращает: (total_commission_usdt, owner_amount_usdt, executor_amount_usdt).
    Минимальная общая комиссия — 25 RUB в эквиваленте USDT.
    При срабатывании минимума сумма делится в том же соотношении,
    что и настроенные проценты сервиса/исполнителя.
    """
    base = float(user_amount_usdt)
    rate = float(rate)
    owner_pct = max(0.0, float(owner_commission))
    executor_pct = max(0.0, float(executor_commission))
    total_pct = owner_pct + executor_pct

    percentage_commission = base * total_pct / 100.0
    minimum_commission = MIN_TOTAL_COMMISSION_RUB / rate
    total_commission = max(percentage_commission, minimum_commission)

    if total_pct > 0:
        owner_amount = total_commission * owner_pct / total_pct
        executor_amount = total_commission * executor_pct / total_pct
    else:
        # Если проценты ещё не настроены, минимум остаётся комиссией сервиса.
        owner_amount = total_commission
        executor_amount = 0.0

    return total_commission, owner_amount, executor_amount

async def fetch_exchange_rate():
    """Получить текущий реальный курс USDT/RUB из CoinGecko и применить
    скидку платформы (EXCHANGE_RATE_MARKUP_PERCENT), чтобы получить курс,
    который используется в расчётах и показывается пользователям."""
    global current_exchange_rate, raw_market_exchange_rate
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://api.coingecko.com/api/v3/simple/price?ids=tether&vs_currencies=rub"
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    rate = data.get("tether", {}).get("rub")
                    if rate:
                        raw_market_exchange_rate = float(rate)
                        current_exchange_rate = raw_market_exchange_rate * (1 - EXCHANGE_RATE_MARKUP_PERCENT / 100.0)
                        print(f"[Exchange Rate] Реальный курс: {raw_market_exchange_rate:.2f} RUB → "
                              f"курс в боте (-{EXCHANGE_RATE_MARKUP_PERCENT:.2f}%): {current_exchange_rate:.2f} RUB")
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
    """Получить курс, который используется в боте (уже со скидкой платформы)."""
    return current_exchange_rate

def get_raw_market_exchange_rate():
    """Получить необработанный реальный рыночный курс (без скидки платформы), для справки/логов."""
    return raw_market_exchange_rate

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

async def init_db():
    global pool
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=10)
    async with pool.acquire() as conn:
        # ВАЖНО: никаких DROP TABLE — данные должны переживать редеплой.
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
            executor_notify_enabled BOOLEAN NOT NULL DEFAULT TRUE,
            executor_blocked BOOLEAN NOT NULL DEFAULT FALSE,
            blocked BOOLEAN NOT NULL DEFAULT FALSE,
            block_reason TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE TABLE IF NOT EXISTS services(
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            min_amount NUMERIC(14,2) NOT NULL DEFAULT 1.0,
            max_amount NUMERIC(14,2) NOT NULL DEFAULT 1000000000.0,
            owner_commission NUMERIC(5,2) NOT NULL DEFAULT 0,
            executor_commission NUMERIC(5,2) NOT NULL DEFAULT 0,
            payment_type TEXT NOT NULL DEFAULT 'phone',
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
            completed_at TIMESTAMPTZ,
            confirmed_at TIMESTAMPTZ,
            disputed_at TIMESTAMPTZ,
            settled_at TIMESTAMPTZ,
            escrow_amount_usdt NUMERIC(18,4) NOT NULL DEFAULT 0,
            payment_method TEXT,
            payment_details TEXT,
            payment_file_id TEXT,
            order_comment TEXT
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
        CREATE UNIQUE INDEX IF NOT EXISTS idx_ratings_order_from ON ratings(order_id, from_user_id);
        CREATE TABLE IF NOT EXISTS order_chat_messages(
            id BIGSERIAL PRIMARY KEY,
            order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
            sender_id BIGINT NOT NULL REFERENCES users(user_id),
            recipient_id BIGINT NOT NULL REFERENCES users(user_id),
            telegram_message_id BIGINT NOT NULL,
            content_type TEXT NOT NULL,
            text_content TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS idx_order_chat_messages_order ON order_chat_messages(order_id, id);
        CREATE TABLE IF NOT EXISTS withdrawal_requests(
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES users(user_id),
            amount NUMERIC(18,4) NOT NULL CHECK (amount > 0),
            wallet TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            admin_comment TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            processed_at TIMESTAMPTZ
        );
        CREATE INDEX IF NOT EXISTS idx_withdrawal_requests_user ON withdrawal_requests(user_id, id);
        CREATE INDEX IF NOT EXISTS idx_withdrawal_requests_status ON withdrawal_requests(status, id);
        """)

        await conn.execute("""
        CREATE TABLE IF NOT EXISTS order_events(
            id BIGSERIAL PRIMARY KEY,
            order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
            actor_id BIGINT REFERENCES users(user_id),
            event_type TEXT NOT NULL,
            details TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS idx_order_events_order ON order_events(order_id, id);
        CREATE TABLE IF NOT EXISTS order_evidence(
            id BIGSERIAL PRIMARY KEY,
            order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
            sender_id BIGINT NOT NULL REFERENCES users(user_id),
            telegram_message_id BIGINT NOT NULL,
            content_type TEXT NOT NULL,
            caption TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS idx_order_evidence_order ON order_evidence(order_id, id);
        CREATE TABLE IF NOT EXISTS notifications(
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
            order_id INTEGER REFERENCES orders(id) ON DELETE CASCADE,
            kind TEXT NOT NULL,
            title TEXT NOT NULL,
            body TEXT NOT NULL DEFAULT '',
            read_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id, id DESC);
        CREATE INDEX IF NOT EXISTS idx_notifications_unread ON notifications(user_id, read_at);

        CREATE TABLE IF NOT EXISTS deposits(
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES users(user_id),
            invoice_id BIGINT NOT NULL UNIQUE,
            amount NUMERIC(18,4) NOT NULL CHECK (amount > 0),
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            paid_at TIMESTAMPTZ
        );
        CREATE INDEX IF NOT EXISTS idx_deposits_user ON deposits(user_id, id);
        CREATE INDEX IF NOT EXISTS idx_deposits_status ON deposits(status, id);

        """)

        # Миграции для старых баз: добавляем колонки, которых может не хватать
        await _add_column_if_missing(conn, "users", "role", "TEXT NOT NULL DEFAULT 'client'")
        await _add_column_if_missing(conn, "users", "executor_name", "TEXT")
        await _add_column_if_missing(conn, "users", "executor_description", "TEXT")
        await _add_column_if_missing(conn, "users", "executor_city", "TEXT")
        await _add_column_if_missing(conn, "users", "executor_available", "BOOLEAN NOT NULL DEFAULT FALSE")
        await _add_column_if_missing(conn, "users", "executor_notify_enabled", "BOOLEAN NOT NULL DEFAULT TRUE")
        # Старые версии использовали wallet для ручного вывода. Адреса больше не собираем:
        # оставляем колонку только для обратной совместимости, но делаем её необязательной.
        await conn.execute("ALTER TABLE withdrawal_requests ALTER COLUMN wallet DROP NOT NULL")
        await _add_column_if_missing(conn, "users", "executor_blocked", "BOOLEAN NOT NULL DEFAULT FALSE")
        await _add_column_if_missing(conn, "users", "blocked", "BOOLEAN NOT NULL DEFAULT FALSE")
        await _add_column_if_missing(conn, "users", "block_reason", "TEXT")
        await _add_column_if_missing(conn, "users", "created_at", "TIMESTAMPTZ NOT NULL DEFAULT now()")
        await _add_column_if_missing(conn, "users", "agreement_accepted_at", "TIMESTAMPTZ")
        await conn.execute("ALTER TABLE users ALTER COLUMN balance TYPE NUMERIC(18,4) USING balance::numeric(18,4)")
        await _add_column_if_missing(conn, "services", "max_amount", "NUMERIC(14,2) NOT NULL DEFAULT 1000000000.0")
        await _add_column_if_missing(conn, "services", "payment_type", "TEXT NOT NULL DEFAULT 'phone'")
        await _add_column_if_missing(conn, "services", "active", "BOOLEAN NOT NULL DEFAULT TRUE")
        await _add_column_if_missing(conn, "services", "created_at", "TIMESTAMPTZ NOT NULL DEFAULT now()")
        await _add_column_if_missing(conn, "orders", "exchange_rate", "NUMERIC(14,4) NOT NULL DEFAULT 100")
        await _add_column_if_missing(conn, "orders", "executor_id", "BIGINT")
        await _add_column_if_missing(conn, "orders", "completed_at", "TIMESTAMPTZ")
        await _add_column_if_missing(conn, "orders", "confirmed_at", "TIMESTAMPTZ")
        await _add_column_if_missing(conn, "orders", "disputed_at", "TIMESTAMPTZ")
        await _add_column_if_missing(conn, "orders", "settled_at", "TIMESTAMPTZ")
        await _add_column_if_missing(conn, "orders", "escrow_amount_usdt", "NUMERIC(18,4) NOT NULL DEFAULT 0")
        await _add_column_if_missing(conn, "orders", "settlement_for", "TEXT")
        await _add_column_if_missing(conn, "orders", "payment_method", "TEXT")
        await _add_column_if_missing(conn, "orders", "payment_details", "TEXT")
        await _add_column_if_missing(conn, "orders", "payment_file_id", "TEXT")
        await _add_column_if_missing(conn, "orders", "order_comment", "TEXT NOT NULL DEFAULT ''")
        # V18: «Карта под оплату» хранит безопасную метку отдельно,
        # а полные реквизиты карты — только в зашифрованном виде.
        # CVV/CVC и OTP/СМС-коды бот не запрашивает и не сохраняет.
        await _add_column_if_missing(conn, "orders", "executor_card_reference", "TEXT")
        await _add_column_if_missing(conn, "orders", "executor_card_encrypted", "TEXT")

        # V16: фиксированный каталог из четырёх услуг и способ реквизитов.
        # Существующие данные не удаляем: недостающие услуги добавляются,
        # а у старых записей только уточняется тип реквизитов.
        service_specs = [
            ("📱 Пополнение мобильного", "Пополнение номера телефона", "phone"),
            ("💳 Перевод на карту", "Перевод средств на банковскую карту", "card"),
            ("📲 Перевод по СБП", "Перевод на номер телефона через СБП", "phone"),
            ("🧾 Оплата по QR", "Оплата по QR-коду: ссылкой или фотографией QR", "qr"),
            ("💳 Карта под оплату", "Исполнитель использует свою карту для оплаты; детали согласуются через чат", "executor_card"),
        ]
        for name, description, payment_type in service_specs:
            row = await conn.fetchrow("SELECT id FROM services WHERE name=$1 LIMIT 1", name)
            if row:
                await conn.execute("UPDATE services SET description=$1, payment_type=$2 WHERE id=$3", description, payment_type, row[0])
            else:
                await conn.execute(
                    "INSERT INTO services(name, description, min_amount, owner_commission, executor_commission, payment_type) VALUES($1, $2, $3, $4, $5, $6)",
                    name, description, 10.0, 5.0, 5.0, payment_type
                )
        # Совместимость с предыдущими названиями без эмодзи.
        await conn.execute("UPDATE services SET payment_type='phone' WHERE name ILIKE '%Пополнение мобильного%'")
        await conn.execute("UPDATE services SET payment_type='card' WHERE name ILIKE '%Перевод на карту%'")
        await conn.execute("UPDATE services SET payment_type='phone' WHERE name ILIKE '%Перевод по СБП%'")
        await conn.execute("UPDATE services SET payment_type='qr' WHERE name ILIKE '%Оплата по QR%'")

        # V10: состояние прочитанных сообщений
        await conn.execute("""CREATE TABLE IF NOT EXISTS order_chat_reads(order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE, user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE, last_read_id BIGINT NOT NULL DEFAULT 0, updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY(order_id,user_id)); CREATE INDEX IF NOT EXISTS idx_order_chat_reads_user ON order_chat_reads(user_id, order_id);""")

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

async def get_user_agreement_accepted(user_id):
    """Принял ли пользователь пользовательское соглашение."""
    async with pool.acquire() as conn:
        value = await conn.fetchval(
            "SELECT agreement_accepted_at FROM users WHERE user_id=$1", user_id
        )
        return value is not None

async def accept_user_agreement(user_id):
    """Зафиксировать факт принятия пользовательского соглашения."""
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET agreement_accepted_at = now() WHERE user_id=$1 AND agreement_accepted_at IS NULL",
            user_id,
        )

async def get_user(user_id):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT user_id, username, balance, role, executor_name, executor_description, executor_city, executor_available, executor_blocked, blocked, executor_notify_enabled FROM users WHERE user_id=$1",
            user_id,
        )

async def get_services():
    async with pool.acquire() as conn:
        return await conn.fetch(
            "SELECT id, name, description, min_amount, owner_commission, executor_commission, payment_type FROM services WHERE active=TRUE ORDER BY id"
        )

async def get_service(service_id):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT id, name, description, min_amount, owner_commission, executor_commission, active, max_amount, payment_type FROM services WHERE id=$1",
            service_id,
        )

async def create_order(user_id, service_id, amount_rub, rate=None, payment_method=None, payment_details=None, payment_file_id=None, order_comment=""):
    """Create an order and reserve the full client payment in escrow."""
    async with pool.acquire() as conn:
        async with conn.transaction():
            service = await conn.fetchrow(
                "SELECT owner_commission, executor_commission, min_amount, max_amount FROM services WHERE id=$1 AND active=TRUE FOR SHARE", service_id
            )
            if not service:
                return None, "service_not_found"
            owner_comm = float(service[0]); executor_comm = float(service[1])
            min_amount = float(service[2]); max_amount = float(service[3])
            rate = float(rate or get_exchange_rate()); amount_rub = float(amount_rub)
            user_amount_usdt = amount_rub / rate
            if user_amount_usdt < min_amount - 1e-9:
                return None, "below_minimum"
            if user_amount_usdt > max_amount + 1e-9:
                return None, "above_maximum"
            commission_usdt, owner_amount, executor_amount = calculate_order_commission(
                user_amount_usdt, rate, owner_comm, executor_comm
            )
            total_amount_usdt = user_amount_usdt + commission_usdt
            balance = await conn.fetchval("SELECT balance FROM users WHERE user_id=$1 FOR UPDATE", user_id)
            if balance is None:
                return None, "user_not_found"
            if float(balance) + 1e-9 < total_amount_usdt:
                return None, "insufficient_balance"
            order_id = await conn.fetchval(
                """INSERT INTO orders(user_id, service_id, amount_rub, exchange_rate, user_amount_usdt,
                    total_amount_usdt, owner_commission_amount, executor_commission_amount, escrow_amount_usdt,
                    payment_method, payment_details, payment_file_id, order_comment)
                   VALUES($1,$2,$3,$4,$5,$6,$7,$8,$6,$9,$10,$11,$12) RETURNING id""",
                user_id, service_id, amount_rub, rate, user_amount_usdt, total_amount_usdt, owner_amount, executor_amount,
                payment_method, payment_details, payment_file_id, (order_comment or "")[:1000])
            await conn.execute("UPDATE users SET balance=balance-$1 WHERE user_id=$2", total_amount_usdt, user_id)
            await conn.execute("INSERT INTO transactions(user_id,order_id,amount,type,description) VALUES($1,$2,$3,'escrow_hold',$4)", user_id, order_id, -total_amount_usdt, f"Резерв по заявке #{order_id}")
            return order_id, "ok"

async def get_orders(user_id):
    async with pool.acquire() as conn:
        return await conn.fetch(
            """SELECT o.id, s.name, o.amount_rub, o.user_amount_usdt, o.total_amount_usdt, o.status, o.executor_id, o.created_at, o.order_comment
               FROM orders o JOIN services s ON s.id = o.service_id
               WHERE o.user_id = $1 ORDER BY o.id DESC LIMIT 20""",
            user_id,
        )

# ---------- Исполнители ----------

async def register_executor(user_id, name, description, city):
    """Зарегистрировать пользователя как исполнителя"""
    async with pool.acquire() as conn:
        await conn.execute(
            """UPDATE users SET role=$1, executor_name=$2, executor_description=$3,
               executor_city=$4, executor_available=$5
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

async def set_executor_notify_enabled(user_id, enabled):
    """Включить/выключить уведомления о новых заявках для исполнителя"""
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET executor_notify_enabled=$1 WHERE user_id=$2",
            enabled, user_id
        )

async def get_available_executors():
    """Получить всех доступных исполнителей, у которых включены уведомления о новых заявках"""
    async with pool.acquire() as conn:
        return await conn.fetch(
            """SELECT user_id, username, executor_name, executor_description, executor_city
               FROM users WHERE role='executor' AND executor_available=TRUE AND executor_blocked=FALSE
                     AND blocked=FALSE AND executor_notify_enabled=TRUE ORDER BY user_id"""
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

        return {
            "completed": completed,
            "avg_rating": avg_rating,
            "total_ratings": total_ratings
        }

async def get_free_orders(limit=20):
    """Получить свободные заявки, доступные исполнителям."""
    async with pool.acquire() as conn:
        return await conn.fetch(
            """SELECT o.id, s.name, o.amount_rub, o.user_amount_usdt,
                      o.executor_commission_amount, o.created_at, o.order_comment
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
                "SELECT role, executor_available, executor_blocked, blocked FROM users WHERE user_id=$1 FOR UPDATE",
                executor_id,
            )
            if not executor or executor[0] != 'executor' or not executor[1] or executor[2] or executor[3]:
                return None, 'unavailable'
            active_order = await conn.fetchval(
                "SELECT id FROM orders WHERE executor_id=$1 AND status IN ('in_progress','awaiting_confirmation','disputed') LIMIT 1",
                executor_id)
            if active_order:
                return None, 'active_exists'
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
            # Статус доступности исполнителя больше не меняется автоматически:
            # он остаётся «Доступен», пока сам не переключит его. Защита от
            # взятия второй активной заявки обеспечивается проверкой active_order выше.
            return order[1], 'ok'

def _get_card_cipher():
    key = os.getenv("CARD_DATA_ENCRYPTION_KEY")
    if not key:
        raise RuntimeError(
            "CARD_DATA_ENCRYPTION_KEY is not set. Generate a Fernet key and add it to the environment."
        )
    if Fernet is None:
        raise RuntimeError("cryptography package is not installed")
    return Fernet(key.encode())

async def set_executor_card_details(order_id, executor_id, card_number, expiry, cardholder):
    """Устаревшая функция V18. Новая версия не сохраняет данные карты.

    Оставлена только для совместимости со старым кодом/данными.
    """
    card_number = re.sub(r"\D", "", card_number or "")
    expiry = (expiry or "").strip()
    cardholder = " ".join((cardholder or "").split())[:120]
    if not (13 <= len(card_number) <= 19):
        return False, "invalid_card"
    if not re.fullmatch(r"(?:0[1-9]|1[0-2])/\d{2}", expiry):
        return False, "invalid_expiry"
    if len(cardholder) < 2:
        return False, "invalid_holder"
    # Простая проверка Луна (Luhn), чтобы не сохранять явно ошибочный PAN.
    total = 0
    parity = len(card_number) % 2
    for i, ch in enumerate(card_number):
        d = int(ch)
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    if total % 10 != 0:
        return False, "invalid_card"

    payload = json.dumps({
        "card_number": card_number,
        "expiry": expiry,
        "cardholder": cardholder,
    }, ensure_ascii=False, separators=(",", ":"))
    encrypted = _get_card_cipher().encrypt(payload.encode()).decode()
    label = f"Карта •••• {card_number[-4:]}"
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """UPDATE orders
               SET executor_card_reference=$1, executor_card_encrypted=$2
               WHERE id=$3 AND executor_id=$4 AND status='in_progress'
               RETURNING id""", label, encrypted, order_id, executor_id)
        return (bool(row), "ok" if row else "unavailable")

async def get_executor_card_details(order_id, executor_id):
    async with pool.acquire() as conn:
        encrypted = await conn.fetchval(
            "SELECT executor_card_encrypted FROM orders WHERE id=$1 AND executor_id=$2",
            order_id, executor_id)
    if not encrypted:
        return None
    try:
        return json.loads(_get_card_cipher().decrypt(encrypted.encode()).decode())
    except (InvalidToken, ValueError, TypeError, json.JSONDecodeError):
        return None

async def set_executor_card_reference(order_id, executor_id, reference):
    """Обратная совместимость со старой V17-меткой. Новые заявки используют set_executor_card_details."""
    reference = (reference or "").strip()[:120]
    if not reference:
        return False
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """UPDATE orders SET executor_card_reference=$1
               WHERE id=$2 AND executor_id=$3 AND status='in_progress'
               RETURNING id""", reference, order_id, executor_id)
        return bool(row)

async def get_executor_card_reference(order_id, executor_id):
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT executor_card_reference FROM orders WHERE id=$1 AND executor_id=$2",
            order_id, executor_id)

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

async def get_executor_orders(executor_id, status=None):
    """Получить заявки исполнителя"""
    async with pool.acquire() as conn:
        if status:
            return await conn.fetch(
                """SELECT o.id, s.name, o.amount_rub, o.user_amount_usdt, o.status,
                          o.user_id, u.username, o.created_at
                   FROM orders o
                   JOIN services s ON s.id = o.service_id
                   JOIN users u ON u.user_id = o.user_id
                   WHERE o.executor_id=$1 AND o.status=$2
                   ORDER BY o.id DESC LIMIT 20""",
                executor_id, status
            )
        else:
            return await conn.fetch(
                """SELECT o.id, s.name, o.amount_rub, o.user_amount_usdt, o.status,
                          o.user_id, u.username, o.created_at
                   FROM orders o
                   JOIN services s ON s.id = o.service_id
                   JOIN users u ON u.user_id = o.user_id
                   WHERE o.executor_id=$1
                   ORDER BY o.id DESC LIMIT 20""",
                executor_id
            )

async def get_executor_active_order(executor_id):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            """SELECT o.id, s.name, o.amount_rub, o.user_amount_usdt, o.total_amount_usdt,
                      o.executor_commission_amount, o.status, o.created_at, o.completed_at, o.disputed_at,
                      o.settlement_for, o.user_id, o.payment_method, o.payment_details, o.payment_file_id, o.order_comment
               FROM orders o JOIN services s ON s.id=o.service_id
               WHERE o.executor_id=$1 AND o.status IN ('in_progress','awaiting_confirmation','disputed')
               ORDER BY o.id DESC LIMIT 1""", executor_id
        )

async def get_executor_history(executor_id, limit=30):
    async with pool.acquire() as conn:
        return await conn.fetch(
            """SELECT o.id, s.name, o.amount_rub, o.user_amount_usdt, o.status,
                      o.settlement_for, o.created_at, o.settled_at
               FROM orders o JOIN services s ON s.id=o.service_id
               WHERE o.executor_id=$1 AND o.status IN ('done','cancelled')
               ORDER BY o.id DESC LIMIT $2""", executor_id, limit
        )

async def get_withdrawal(withdrawal_id):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            """SELECT w.id, w.user_id, u.username, w.amount, w.status, w.created_at
               FROM withdrawal_requests w JOIN users u ON u.user_id=w.user_id
               WHERE w.id=$1""", withdrawal_id
        )

async def get_pending_withdrawals(limit=30):
    async with pool.acquire() as conn:
        return await conn.fetch(
            """SELECT w.id, w.user_id, u.username, w.amount, w.wallet, w.status, w.created_at
               FROM withdrawal_requests w JOIN users u ON u.user_id=w.user_id
               WHERE w.status='pending' ORDER BY w.id ASC LIMIT $1""", limit
        )

async def create_withdrawal_request(user_id, amount):
    amount=float(amount)
    if amount <= 0:
        return None, 'invalid'
    async with pool.acquire() as conn:
        async with conn.transaction():
            user=await conn.fetchrow("SELECT balance FROM users WHERE user_id=$1 FOR UPDATE", user_id)
            if not user:
                return None, 'user_not_found'
            pending=await conn.fetchval("SELECT COUNT(*) FROM withdrawal_requests WHERE user_id=$1 AND status='pending'", user_id)
            if pending:
                return None, 'pending_exists'
            if float(user[0]) + 1e-9 < amount:
                return None, 'insufficient_balance'
            wid=await conn.fetchval(
                "INSERT INTO withdrawal_requests(user_id,amount,wallet) VALUES($1,$2,NULL) RETURNING id",
                user_id, amount)
            await conn.execute("UPDATE users SET balance=balance-$1 WHERE user_id=$2", amount, user_id)
            await conn.execute(
                "INSERT INTO transactions(user_id,amount,type,description) VALUES($1,$2,'withdrawal_hold',$3)",
                user_id, -amount, f"Резерв на вывод #{wid}")
            return wid, 'ok'

async def approve_withdrawal(withdrawal_id, admin_comment=''):
    async with pool.acquire() as conn:
        async with conn.transaction():
            row=await conn.fetchrow("SELECT user_id,amount,status,wallet FROM withdrawal_requests WHERE id=$1 FOR UPDATE", withdrawal_id)
            if not row or row[2] != 'pending':
                return None
            await conn.execute("UPDATE withdrawal_requests SET status='paid', admin_comment=$1, processed_at=now() WHERE id=$2", admin_comment, withdrawal_id)
            await conn.execute(
                "INSERT INTO transactions(user_id,amount,type,description) VALUES($1,$2,'withdrawal_paid',$3)",
                row[0], 0, f"Вывод #{withdrawal_id} выплачен")
            return row[0], float(row[1]), row[3]

async def reject_withdrawal(withdrawal_id, admin_comment=''):
    async with pool.acquire() as conn:
        async with conn.transaction():
            row=await conn.fetchrow("SELECT user_id,amount,status FROM withdrawal_requests WHERE id=$1 FOR UPDATE", withdrawal_id)
            if not row or row[2] != 'pending':
                return None
            amount=float(row[1])
            await conn.execute("UPDATE users SET balance=balance+$1 WHERE user_id=$2", amount, row[0])
            await conn.execute("UPDATE withdrawal_requests SET status='rejected', admin_comment=$1, processed_at=now() WHERE id=$2", admin_comment, withdrawal_id)
            await conn.execute(
                "INSERT INTO transactions(user_id,amount,type,description) VALUES($1,$2,'withdrawal_refund',$3)",
                row[0], amount, f"Возврат вывода #{withdrawal_id}")
            return row[0], amount

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

# ---------- Рейтинги ----------

async def add_rating(order_id, from_user_id, to_user_id, stars, comment=""):
    """Добавить оценку"""
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO ratings(order_id, from_user_id, to_user_id, stars, comment)
               VALUES($1, $2, $3, $4, $5)""",
            order_id, from_user_id, to_user_id, stars, comment
        )

async def has_rating(order_id, from_user_id=None):
    """Проверить, есть ли уже оценка для этой заявки (опционально — от конкретного автора)."""
    async with pool.acquire() as conn:
        if from_user_id is not None:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM ratings WHERE order_id=$1 AND from_user_id=$2",
                order_id, from_user_id
            )
        else:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM ratings WHERE order_id=$1",
                order_id
            )
        return bool(count)

async def submit_order_rating(order_id, client_id, stars):
    """Атомарно зафиксировать оценку клиента исполнителю по завершённой заявке.

    Возвращает (executor_id, ok_flag, reason). reason — код причины отказа:
    'not_found' | 'not_owner' | 'no_executor' | 'not_done' | 'already_rated'.
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT user_id, executor_id, status FROM orders WHERE id=$1 FOR UPDATE", order_id
            )
            if not row:
                return None, False, 'not_found'
            if row[0] != client_id:
                return None, False, 'not_owner'
            if not row[1]:
                return None, False, 'no_executor'
            if row[2] != 'done':
                return None, False, 'not_done'
            already = await conn.fetchval(
                "SELECT COUNT(*) FROM ratings WHERE order_id=$1 AND from_user_id=$2", order_id, client_id
            )
            if already:
                return row[1], False, 'already_rated'
            await conn.execute(
                """INSERT INTO ratings(order_id, from_user_id, to_user_id, stars)
                   VALUES($1, $2, $3, $4)""",
                order_id, client_id, row[1], stars
            )
            return row[1], True, 'ok'

# ---------- Анонимный чат по заявке ----------

CHAT_OPEN_STATUSES = ("in_progress", "awaiting_confirmation", "disputed")

async def get_order_chat_peer(order_id, user_id):
    """
    Вернуть собеседника только если user_id является клиентом или назначенным
    исполнителем данной заявки. Username намеренно не возвращается.
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT id, user_id, executor_id, status, service_id
               FROM orders WHERE id=$1""", order_id
        )
        if not row or row[3] not in CHAT_OPEN_STATUSES or not row[2]:
            return None
        if row[1] == user_id:
            return {"order_id": row[0], "peer_id": row[2], "side": "client", "status": row[3]}
        if row[2] == user_id:
            return {"order_id": row[0], "peer_id": row[1], "side": "executor", "status": row[3]}
        return None

async def save_order_chat_message(order_id, sender_id, recipient_id, telegram_message_id, content_type, text_content=None):
    """Сохранить технический журнал сообщения чата без username/контактных данных."""
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO order_chat_messages(
                    order_id, sender_id, recipient_id, telegram_message_id, content_type, text_content
               ) VALUES($1,$2,$3,$4,$5,$6)""",
            order_id, sender_id, recipient_id, telegram_message_id, content_type, text_content
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
                      o.executor_id, o.created_at, o.payment_method, o.payment_details, o.payment_file_id, o.order_comment
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
                      o.executor_id, o.created_at, o.payment_method, o.payment_details, o.payment_file_id, o.order_comment
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
            await conn.execute("UPDATE orders SET status='done', confirmed_at=COALESCE(confirmed_at, now()), settled_at=now(), escrow_amount_usdt=0, settlement_for='executor' WHERE id=$1", order_id)
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
            await conn.execute("UPDATE orders SET status='cancelled', settled_at=now(), escrow_amount_usdt=0, settlement_for='client' WHERE id=$1", order_id)
            await conn.execute("INSERT INTO transactions(user_id,order_id,amount,type,description) VALUES($1,$2,$3,'escrow_refund',$4)", row[0], order_id, refund, f"Возврат по спору #{order_id}")
            return row[0], refund

async def dispute_order_by_admin(order_id):
    async with pool.acquire() as conn:
        row = await conn.fetchrow("UPDATE orders SET status='disputed', disputed_at=now() WHERE id=$1 AND status='awaiting_confirmation' RETURNING executor_id", order_id)
        return row[0] if row else None

async def set_order_status(order_id, status):
    """Возвращает True, если статус реально изменён, и False, если заявку
    нельзя перевести в этот статус (уже завершена/отменена и т.п.) —
    в этом случае строка НЕ трогается, чтобы не рассинхронизировать
    статус с уже выплаченными/возвращёнными деньгами."""
    async with pool.acquire() as conn:
        async with conn.transaction():
            if status == "done":
                status = "awaiting_confirmation"
            if status == "cancelled":
                row = await conn.fetchrow("SELECT user_id, escrow_amount_usdt, status FROM orders WHERE id=$1 FOR UPDATE", order_id)
                if not row or row[2] in ('done', 'cancelled'):
                    # Заявка уже финализирована (деньги выплачены/возвращены) —
                    # статус трогать нельзя, иначе он разъедется с фактом выплаты.
                    return False
                refund = float(row[1])
                if refund > 0:
                    await conn.execute("UPDATE users SET balance=balance+$1 WHERE user_id=$2", refund, row[0])
                    await conn.execute("INSERT INTO transactions(user_id,order_id,amount,type,description) VALUES($1,$2,$3,'escrow_refund',$4)", row[0], order_id, refund, f"Возврат по отменённой заявке #{order_id}")
                await conn.execute("UPDATE orders SET escrow_amount_usdt=0, status='cancelled', settled_at=now(), settlement_for='cancelled' WHERE id=$1", order_id)
                return True
            if status == "awaiting_confirmation":
                result = await conn.execute("UPDATE orders SET status=$1, completed_at=COALESCE(completed_at, now()) WHERE id=$2 AND status NOT IN ('done','cancelled')", status, order_id)
            else:
                result = await conn.execute("UPDATE orders SET status=$1, settlement_for=CASE WHEN $1='cancelled' THEN 'cancelled' ELSE settlement_for END WHERE id=$2 AND status NOT IN ('done','cancelled')", status, order_id)
            return result.split()[-1] != "0"

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
                "SELECT user_id, username, balance, role, executor_blocked, blocked, block_reason FROM users WHERE user_id=$1",
                int(query),
            )
        return await conn.fetchrow(
            "SELECT user_id, username, balance, role, executor_blocked, blocked, block_reason FROM users WHERE username ILIKE $1",
            query,
        )

async def adjust_balance(user_id, delta, admin_comment=None):
    """Изменяет баланс пользователя вручную (админом) и логирует операцию
    в историю транзакций, чтобы она была видна в «Истории операций»."""
    async with pool.acquire() as conn:
        async with conn.transaction():
            new_balance = await conn.fetchval(
                "UPDATE users SET balance = balance + $1 WHERE user_id=$2 RETURNING balance",
                delta, user_id,
            )
            if new_balance is None:
                return None
            kind = "admin_credit" if delta >= 0 else "admin_debit"
            description = admin_comment or (
                "Начисление администратором" if delta >= 0 else "Списание администратором"
            )
            await conn.execute(
                "INSERT INTO transactions(user_id,amount,type,description) VALUES($1,$2,$3,$4)",
                user_id, delta, kind, description,
            )
            return new_balance

# ---------- Депозиты (пополнение через xRocket) ----------

async def create_deposit(user_id, invoice_id, amount):
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "INSERT INTO deposits(user_id, invoice_id, amount) VALUES($1,$2,$3) RETURNING id",
            user_id, invoice_id, amount,
        )

async def get_deposit_by_invoice(invoice_id):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT id, user_id, invoice_id, amount, status FROM deposits WHERE invoice_id=$1",
            invoice_id,
        )

async def mark_deposit_paid(invoice_id, paid_amount=None):
    """Идемпотентно зачисляет депозит на баланс пользователя: если счёт с
    таким invoice_id уже обработан (или не найден) — ничего не делает и
    возвращает None. Так безопасно вызывать эту функцию и из вебхука
    xRocket, и из ручной проверки статуса — двойного начисления не будет."""
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT id, user_id, amount, status FROM deposits WHERE invoice_id=$1 FOR UPDATE",
                invoice_id,
            )
            if row is None or row["status"] != "pending":
                return None
            credit = float(paid_amount) if paid_amount else float(row["amount"])
            await conn.execute("UPDATE deposits SET status='paid', paid_at=now() WHERE id=$1", row["id"])
            await conn.execute("UPDATE users SET balance = balance + $1 WHERE user_id=$2", credit, row["user_id"])
            await conn.execute(
                "INSERT INTO transactions(user_id,amount,type,description) VALUES($1,$2,'deposit',$3)",
                row["user_id"], credit, f"Пополнение через xRocket (счёт #{invoice_id})",
            )
            return {"deposit_id": row["id"], "user_id": row["user_id"], "amount": credit}

async def mark_deposit_expired(invoice_id):
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE deposits SET status='expired' WHERE invoice_id=$1 AND status='pending'",
            invoice_id,
        )

async def get_user_transactions(user_id, limit=30):
    async with pool.acquire() as conn:
        return await conn.fetch(
            """SELECT id, amount, type, description, created_at
               FROM transactions WHERE user_id=$1 ORDER BY id DESC LIMIT $2""",
            user_id, limit
        )

async def get_disputed_orders(limit=30):
    async with pool.acquire() as conn:
        return await conn.fetch(
            """SELECT o.id, o.user_id, cu.username AS client_username,
                      o.executor_id, eu.username AS executor_username,
                      s.name, o.amount_rub, o.user_amount_usdt, o.total_amount_usdt,
                      o.status, o.created_at, o.disputed_at, o.settlement_for
               FROM orders o
               JOIN services s ON s.id=o.service_id
               JOIN users cu ON cu.user_id=o.user_id
               LEFT JOIN users eu ON eu.user_id=o.executor_id
               WHERE o.status='disputed'
               ORDER BY o.id DESC LIMIT $1""", limit
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

# ---------- V10: chat read state / audit ----------
async def init_v10_db():
    async with pool.acquire() as conn:
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS order_chat_reads(
            order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
            user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
            last_read_id BIGINT NOT NULL DEFAULT 0,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY(order_id, user_id)
        );
        CREATE INDEX IF NOT EXISTS idx_order_chat_reads_user ON order_chat_reads(user_id, order_id);
        """)

async def get_chat_unread_count(order_id, user_id):
    async with pool.acquire() as conn:
        return await conn.fetchval("""
            SELECT COUNT(*) FROM order_chat_messages m
            WHERE m.order_id=$1 AND m.recipient_id=$2
              AND m.id > COALESCE((SELECT last_read_id FROM order_chat_reads WHERE order_id=$1 AND user_id=$2),0)
        """, order_id, user_id)

async def get_chat_unread_for_orders(order_ids, user_id):
    if not order_ids:
        return {}
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT m.order_id, COUNT(*) AS cnt
            FROM order_chat_messages m
            WHERE m.order_id = ANY($1::int[]) AND m.recipient_id=$2
              AND m.id > COALESCE((SELECT r.last_read_id FROM order_chat_reads r WHERE r.order_id=m.order_id AND r.user_id=$2),0)
            GROUP BY m.order_id
        """, list(order_ids), user_id)
        return {int(r[0]): int(r[1]) for r in rows}

async def mark_chat_read(order_id, user_id):
    async with pool.acquire() as conn:
        last_id = await conn.fetchval("SELECT COALESCE(MAX(id),0) FROM order_chat_messages WHERE order_id=$1", order_id)
        await conn.execute("""
            INSERT INTO order_chat_reads(order_id,user_id,last_read_id)
            VALUES($1,$2,$3)
            ON CONFLICT(order_id,user_id) DO UPDATE SET last_read_id=EXCLUDED.last_read_id, updated_at=now()
        """, order_id, user_id, last_id)

async def get_recent_chat_messages(order_id, limit=12):
    async with pool.acquire() as conn:
        return await conn.fetch("""
            SELECT id,sender_id,content_type,text_content,created_at
            FROM order_chat_messages WHERE order_id=$1 ORDER BY id DESC LIMIT $2
        """, order_id, limit)

async def get_order_counts_by_status():
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT status, COUNT(*) cnt FROM orders GROUP BY status")
        return {r[0]: int(r[1]) for r in rows}

async def get_executor_detailed_stats(executor_id):
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT
              COUNT(*) FILTER (WHERE status='done') AS completed,
              COUNT(*) FILTER (WHERE status='cancelled') AS cancelled,
              COUNT(*) FILTER (WHERE status='disputed') AS disputes,
              COUNT(*) FILTER (WHERE status='done' AND settlement_for='executor') AS dispute_executor_wins,
              COUNT(*) FILTER (WHERE status='cancelled' AND settlement_for='client') AS dispute_client_wins,
              COALESCE(SUM(CASE WHEN status='done' THEN user_amount_usdt + executor_commission_amount ELSE 0 END),0) AS earned
            FROM orders WHERE executor_id=$1
        """, executor_id)
        rating = await conn.fetchrow("SELECT COALESCE(AVG(stars),0), COUNT(*) FROM ratings WHERE to_user_id=$1", executor_id)
        return {
            'completed': int(row[0] or 0), 'cancelled': int(row[1] or 0), 'disputes': int(row[2] or 0),
            'executor_wins': int(row[3] or 0), 'client_wins': int(row[4] or 0), 'earned': float(row[5] or 0),
            'rating': float(rating[0] or 0), 'ratings': int(rating[1] or 0)
        }


async def log_order_event(order_id, actor_id, event_type, details=''):
    await pool.execute("INSERT INTO order_events(order_id,actor_id,event_type,details) VALUES($1,$2,$3,$4)", order_id, actor_id, event_type, details[:2000])

async def get_order_events(order_id, limit=100):
    return await pool.fetch("""SELECT e.id,e.actor_id,e.event_type,e.details,e.created_at,u.role FROM order_events e LEFT JOIN users u ON u.user_id=e.actor_id WHERE e.order_id=$1 ORDER BY e.id DESC LIMIT $2""", order_id, limit)

async def add_order_evidence(order_id, sender_id, telegram_message_id, content_type, caption=''):
    return await pool.fetchval("INSERT INTO order_evidence(order_id,sender_id,telegram_message_id,content_type,caption) VALUES($1,$2,$3,$4,$5) RETURNING id", order_id, sender_id, telegram_message_id, content_type, (caption or '')[:1000])

async def get_order_evidence(order_id, limit=50):
    return await pool.fetch("""SELECT id,sender_id,telegram_message_id,content_type,caption,created_at FROM order_evidence WHERE order_id=$1 ORDER BY id DESC LIMIT $2""", order_id, limit)

async def create_notification(user_id, kind, title, body='', order_id=None):
    return await pool.fetchval("INSERT INTO notifications(user_id,order_id,kind,title,body) VALUES($1,$2,$3,$4,$5) RETURNING id", user_id, order_id, kind, title[:200], body[:2000])

async def get_notifications(user_id, limit=30):
    return await pool.fetch("SELECT id,order_id,kind,title,body,read_at,created_at FROM notifications WHERE user_id=$1 ORDER BY id DESC LIMIT $2", user_id, limit)

async def get_unread_notifications_count(user_id):
    return await pool.fetchval("SELECT COUNT(*) FROM notifications WHERE user_id=$1 AND read_at IS NULL", user_id)

async def mark_notifications_read(user_id):
    await pool.execute("UPDATE notifications SET read_at=now() WHERE user_id=$1 AND read_at IS NULL", user_id)

async def set_user_blocked(user_id, blocked=True):
    await pool.execute("UPDATE users SET executor_blocked=$2 WHERE user_id=$1", user_id, blocked)
    if blocked:
        await pool.execute("UPDATE users SET executor_available=FALSE WHERE user_id=$1", user_id)

async def get_executor_profile(user_id):
    return await pool.fetchrow("""SELECT u.user_id,u.username,u.executor_name,u.executor_description,u.executor_city,u.executor_available,u.executor_blocked,COALESCE(AVG(r.stars),0),COUNT(r.id) FROM users u LEFT JOIN ratings r ON r.to_user_id=u.user_id WHERE u.user_id=$1 GROUP BY u.user_id""", user_id)

async def get_executor_history_detailed(executor_id, limit=50):
    return await pool.fetch("""SELECT o.id,s.name,o.amount_rub,o.total_amount_usdt,o.status,o.settlement_for,o.created_at,o.completed_at,o.confirmed_at,o.disputed_at,o.settled_at FROM orders o JOIN services s ON s.id=o.service_id WHERE o.executor_id=$1 ORDER BY o.id DESC LIMIT $2""", executor_id, limit)

async def get_users_admin(limit=50):
    return await pool.fetch("""SELECT u.user_id,u.username,u.role,u.balance,u.executor_available,u.executor_blocked,u.created_at,COUNT(o.id) AS orders FROM users u LEFT JOIN orders o ON o.user_id=u.user_id GROUP BY u.user_id ORDER BY u.created_at DESC LIMIT $1""", limit)

async def get_service_usage(service_id):
    return await pool.fetchrow("SELECT COUNT(*) AS orders, COUNT(*) FILTER (WHERE status='done') AS done FROM orders WHERE service_id=$1", service_id)

async def get_all_services_stats():
    return await pool.fetch("""SELECT s.id,s.name,s.active,COUNT(o.id) orders,COUNT(o.id) FILTER(WHERE o.status='done') done FROM services s LEFT JOIN orders o ON o.service_id=s.id GROUP BY s.id ORDER BY s.id""")


async def get_user_blocked(user_id):
    return bool(await pool.fetchval("SELECT blocked FROM users WHERE user_id=$1", user_id))

async def set_user_blocked_only(user_id, blocked=True, reason=''):
    await pool.execute("UPDATE users SET blocked=$2, block_reason=$3 WHERE user_id=$1", user_id, blocked, (reason or '')[:1000] if blocked else None)
    if blocked:
        await pool.execute("UPDATE users SET executor_available=FALSE WHERE user_id=$1", user_id)

async def get_user_block_info(user_id):
    return await pool.fetchrow("SELECT blocked,block_reason FROM users WHERE user_id=$1", user_id)

async def list_executors_admin(limit=50):
    return await pool.fetch("""SELECT u.user_id,u.username,u.executor_name,u.executor_available,u.executor_blocked,u.balance,COUNT(DISTINCT o.id) FILTER(WHERE o.status='done') completed,COALESCE(AVG(r.stars),0) rating,COUNT(DISTINCT r.id) ratings FROM users u LEFT JOIN orders o ON o.executor_id=u.user_id LEFT JOIN ratings r ON r.to_user_id=u.user_id WHERE u.role='executor' GROUP BY u.user_id ORDER BY u.user_id DESC LIMIT $1""", limit)

async def set_service_max_amount(service_id, max_amount):
    await pool.execute("UPDATE services SET max_amount=$2 WHERE id=$1", service_id, max_amount)

async def get_service_limits(service_id):
    return await pool.fetchrow("SELECT min_amount,max_amount FROM services WHERE id=$1", service_id)
