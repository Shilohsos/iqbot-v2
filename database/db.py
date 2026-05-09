"""
Database connection and schema initialization.
All tables created on first connection.
"""
import sqlite3
from config import DATABASE_PATH
from utils.logger import get_logger

_log = get_logger("db")

SCHEMA = """
-- Users
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER NOT NULL UNIQUE,
    telegram_username TEXT,
    iq_user_id INTEGER UNIQUE,
    tier TEXT NOT NULL DEFAULT 'PENDING',
    approval_status TEXT NOT NULL DEFAULT 'PENDING',
    rejection_reason TEXT,
    referrer_check_passed INTEGER DEFAULT 0,
    token TEXT UNIQUE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_active_at TEXT,
    last_trade_at TEXT
);

-- Accounts (IQ Option credentials)
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    email_encrypted TEXT NOT NULL DEFAULT '',
    password_encrypted TEXT NOT NULL DEFAULT '',
    ssid TEXT,
    ssid_at TEXT,
    platform_id INTEGER NOT NULL,
    refresh_token TEXT,
    token_expires_at TEXT,
    real_balance_id INTEGER,
    real_balance_amount REAL DEFAULT 0,
    real_balance_currency TEXT DEFAULT 'USD',
    practice_balance_id INTEGER,
    practice_balance_amount REAL DEFAULT 0,
    practice_balance_currency TEXT DEFAULT 'USD',
    is_active INTEGER DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Trades
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    pair TEXT NOT NULL,
    direction TEXT NOT NULL,
    amount REAL NOT NULL,
    duration_seconds INTEGER NOT NULL,
    iq_option_id INTEGER UNIQUE,
    bias_at_entry REAL,
    confidence_at_entry REAL,
    result TEXT,
    pnl REAL DEFAULT 0,
    balance_type TEXT,
    opened_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    closed_at TEXT
);

-- Market Bias
CREATE TABLE IF NOT EXISTS market_bias (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset TEXT NOT NULL,
    timeframe_seconds INTEGER NOT NULL,
    bullish_percent REAL NOT NULL,
    bearish_percent REAL NOT NULL,
    confidence REAL NOT NULL,
    rsi_value REAL,
    ema_signal TEXT,
    macd_signal TEXT,
    last_close REAL,
    candles_used INTEGER,
    is_suspended INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(asset, timeframe_seconds)
);
CREATE INDEX IF NOT EXISTS idx_bias_asset_tf ON market_bias(asset, timeframe_seconds);
CREATE INDEX IF NOT EXISTS idx_bias_updated ON market_bias(updated_at);

-- Affiliate events
CREATE TABLE IF NOT EXISTS affiliate_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    iq_user_id INTEGER NOT NULL,
    raw_message TEXT,
    parsed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_aff_iqid ON affiliate_events(iq_user_id);

-- Funnel events
CREATE TABLE IF NOT EXISTS funnel_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER,
    event_type TEXT NOT NULL,
    metadata TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Broadcasts
CREATE TABLE IF NOT EXISTS broadcasts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    admin_id INTEGER NOT NULL,
    target_segment TEXT NOT NULL,
    message_text TEXT,
    image_path TEXT,
    button_text TEXT,
    button_url TEXT,
    sent_count INTEGER DEFAULT 0,
    sent_at TEXT
);

-- Leaderboard
CREATE TABLE IF NOT EXISTS leaderboard (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rank INTEGER NOT NULL,
    display_name TEXT NOT NULL,
    profit_amount REAL NOT NULL,
    profit_currency TEXT DEFAULT 'USD',
    period TEXT NOT NULL,
    updated_by_admin INTEGER NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Admin actions audit
CREATE TABLE IF NOT EXISTS admin_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    admin_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    target_user_id INTEGER,
    details TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


def get_connection() -> sqlite3.Connection:
    """Get a synchronous SQLite connection (for simple ops)."""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Initialize schema. Safe to call multiple times."""
    conn = get_connection()
    conn.executescript(SCHEMA)
    # ── Inline migrations (idempotent via PRAGMA table_info checks) ──
    bias_cols = {row[1] for row in conn.execute("PRAGMA table_info(market_bias)")}
    if 'is_suspended' not in bias_cols:
        conn.execute(
            "ALTER TABLE market_bias ADD COLUMN is_suspended INTEGER NOT NULL DEFAULT 0"
        )
    acct_cols = {row[1] for row in conn.execute("PRAGMA table_info(accounts)")}
    if 'refresh_token' not in acct_cols:
        conn.execute("ALTER TABLE accounts ADD COLUMN refresh_token TEXT")
    if 'token_expires_at' not in acct_cols:
        conn.execute("ALTER TABLE accounts ADD COLUMN token_expires_at TEXT")
    conn.commit()
    conn.close()
    _log.info(f"Database initialized at {DATABASE_PATH}")
