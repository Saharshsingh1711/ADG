"""
Autonomous Database Guardian — Database Initialization
Creates and seeds analytics.db with sample tables: users, orders, system_logs.
Idempotent: safe to run multiple times.
"""

import asyncio
import sys
from pathlib import Path

import aiosqlite

DB_PATH = Path(__file__).parent / "analytics.db"

# ── DDL ──────────────────────────────────────────────────────────────────────

CREATE_USERS = """
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    username    TEXT    NOT NULL UNIQUE,
    email       TEXT    NOT NULL,
    role        TEXT    NOT NULL DEFAULT 'viewer',
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);
"""

CREATE_ORDERS = """
CREATE TABLE IF NOT EXISTS orders (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    product     TEXT    NOT NULL,
    amount      REAL    NOT NULL,
    status      TEXT    NOT NULL DEFAULT 'pending',
    ordered_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);
"""

CREATE_SYSTEM_LOGS = """
CREATE TABLE IF NOT EXISTS system_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    level       TEXT    NOT NULL,
    message     TEXT    NOT NULL,
    source      TEXT    NOT NULL,
    logged_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);
"""

# ── Seed Data ────────────────────────────────────────────────────────────────

SEED_USERS = """
INSERT OR IGNORE INTO users (username, email, role, created_at) VALUES
    ('alice',    'alice@example.com',    'admin',   '2024-01-15 09:30:00'),
    ('bob',      'bob@example.com',      'editor',  '2024-02-20 14:15:00'),
    ('charlie',  'charlie@example.com',  'viewer',  '2024-03-10 11:00:00'),
    ('diana',    'diana@example.com',    'editor',  '2024-04-05 16:45:00'),
    ('eve',      'eve@example.com',      'admin',   '2024-05-12 08:20:00'),
    ('frank',    'frank@example.com',    'viewer',  '2024-06-18 13:10:00'),
    ('grace',    'grace@example.com',    'viewer',  '2024-07-22 10:55:00'),
    ('heidi',    'heidi@example.com',    'editor',  '2024-08-30 17:30:00'),
    ('ivan',     'ivan@example.com',     'viewer',  '2024-09-14 09:00:00'),
    ('judy',     'judy@example.com',     'admin',   '2024-10-01 12:00:00');
"""

SEED_ORDERS = """
INSERT OR IGNORE INTO orders (user_id, product, amount, status, ordered_at) VALUES
    (1, 'Enterprise License',      4999.99, 'completed',  '2024-03-01 10:00:00'),
    (2, 'Pro Subscription',         299.00, 'completed',  '2024-03-15 11:30:00'),
    (1, 'Data Add-on Pack',          99.50, 'completed',  '2024-04-02 09:15:00'),
    (3, 'Starter Plan',              49.99, 'pending',    '2024-04-20 14:00:00'),
    (4, 'Pro Subscription',         299.00, 'completed',  '2024-05-10 16:30:00'),
    (5, 'Enterprise License',      4999.99, 'shipped',    '2024-05-25 08:45:00'),
    (2, 'API Access Token',         149.00, 'completed',  '2024-06-05 12:00:00'),
    (6, 'Starter Plan',              49.99, 'cancelled',  '2024-06-18 10:30:00'),
    (7, 'Pro Subscription',         299.00, 'pending',    '2024-07-01 15:00:00'),
    (3, 'Data Add-on Pack',          99.50, 'completed',  '2024-07-15 11:00:00'),
    (8, 'Enterprise License',      4999.99, 'shipped',    '2024-08-01 09:30:00'),
    (9, 'Starter Plan',              49.99, 'completed',  '2024-08-20 13:45:00'),
    (10,'Pro Subscription',         299.00, 'completed',  '2024-09-05 10:15:00'),
    (4, 'API Access Token',         149.00, 'pending',    '2024-09-18 16:00:00'),
    (5, 'Data Add-on Pack',          99.50, 'completed',  '2024-10-01 08:00:00');
"""

SEED_SYSTEM_LOGS = """
INSERT OR IGNORE INTO system_logs (level, message, source, logged_at) VALUES
    ('INFO',    'Application started',              'app',        '2024-01-01 00:00:00'),
    ('INFO',    'Database migration completed',     'migration',  '2024-01-01 00:01:00'),
    ('WARNING', 'High memory usage detected',       'monitor',    '2024-02-14 03:22:00'),
    ('ERROR',   'Failed to send notification email', 'notifier',  '2024-02-15 08:10:00'),
    ('INFO',    'User alice logged in',             'auth',       '2024-03-01 09:30:00'),
    ('INFO',    'Backup completed successfully',    'backup',     '2024-03-15 02:00:00'),
    ('WARNING', 'Disk usage above 80%',             'monitor',    '2024-04-10 06:45:00'),
    ('ERROR',   'Payment gateway timeout',          'billing',    '2024-04-12 14:30:00'),
    ('INFO',    'New user bob registered',          'auth',       '2024-04-20 14:15:00'),
    ('DEBUG',   'Cache invalidated for key users',  'cache',      '2024-05-01 11:00:00'),
    ('INFO',    'Scheduled report generated',       'reports',    '2024-05-15 06:00:00'),
    ('ERROR',   'SSL certificate renewal failed',   'security',  '2024-06-01 00:05:00'),
    ('WARNING', 'API rate limit approaching',       'gateway',    '2024-06-20 15:30:00'),
    ('INFO',    'System update applied v2.3.1',     'updater',    '2024-07-04 03:00:00'),
    ('INFO',    'User eve promoted to admin',       'auth',       '2024-07-10 09:00:00'),
    ('ERROR',   'Database connection pool exhausted','db',        '2024-08-05 18:22:00'),
    ('WARNING', 'Slow query detected (>5s)',        'db',         '2024-08-20 12:15:00'),
    ('INFO',    'Feature flag dark_mode enabled',   'config',     '2024-09-01 10:00:00'),
    ('DEBUG',   'GC pause 120ms',                   'runtime',    '2024-09-10 04:30:00'),
    ('INFO',    'End-of-quarter audit completed',   'compliance', '2024-09-30 23:59:00');
"""


async def initialize_database() -> None:
    """Create tables and insert seed data into analytics.db."""
    print(f"📦 Initializing database at: {DB_PATH}")

    async with aiosqlite.connect(str(DB_PATH)) as db:
        # Enable foreign keys
        await db.execute("PRAGMA foreign_keys = ON;")

        # Create tables
        await db.execute(CREATE_USERS)
        await db.execute(CREATE_ORDERS)
        await db.execute(CREATE_SYSTEM_LOGS)
        print("   ✅ Tables created (users, orders, system_logs)")

        # Seed data
        await db.executescript(SEED_USERS)
        await db.executescript(SEED_ORDERS)
        await db.executescript(SEED_SYSTEM_LOGS)
        print("   ✅ Seed data inserted")

        await db.commit()

    # Verify
    async with aiosqlite.connect(str(DB_PATH)) as db:
        for table in ("users", "orders", "system_logs"):
            cursor = await db.execute(f"SELECT COUNT(*) FROM {table}")
            row = await cursor.fetchone()
            count = row[0] if row else 0
            print(f"   📊 {table}: {count} rows")

    print("🎉 Database initialization complete!")


if __name__ == "__main__":
    try:
        asyncio.run(initialize_database())
    except Exception as exc:
        print(f"❌ Initialization failed: {exc}", file=sys.stderr)
        sys.exit(1)
