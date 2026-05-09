"""Trade model operations."""
from database.db import get_connection
from typing import Optional


def log_trade(
    user_id: int, pair: str, direction: str, amount: float,
    duration_seconds: int, iq_option_id: int = None,
    bias_at_entry: float = None, confidence_at_entry: float = None,
    balance_type: str = 'PRACTICE'
) -> int:
    conn = get_connection()
    cursor = conn.execute(
        """INSERT INTO trades
           (user_id, pair, direction, amount, duration_seconds,
            iq_option_id, bias_at_entry, confidence_at_entry,
            balance_type, result)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING')""",
        (user_id, pair, direction, amount, duration_seconds,
         iq_option_id, bias_at_entry, confidence_at_entry, balance_type)
    )
    # Update user's last_trade_at
    conn.execute(
        "UPDATE users SET last_active_at=CURRENT_TIMESTAMP, last_trade_at=CURRENT_TIMESTAMP WHERE id=?",
        (user_id,)
    )
    conn.commit()
    trade_id = cursor.lastrowid
    conn.close()
    return trade_id


def update_trade_result(iq_option_id: int, result: str, pnl: float):
    conn = get_connection()
    conn.execute(
        """UPDATE trades
           SET result=?, pnl=?, closed_at=CURRENT_TIMESTAMP
           WHERE iq_option_id=?""",
        (result, pnl, iq_option_id)
    )
    conn.commit()
    conn.close()


def get_daily_summary() -> dict:
    conn = get_connection()
    row = conn.execute(
        """SELECT
              COUNT(*) as count,
              COALESCE(SUM(amount), 0) as volume,
              COALESCE(SUM(CASE WHEN result='WIN' THEN pnl
                           WHEN result='LOSS' THEN -amount
                           ELSE 0 END), 0) as pnl,
              COUNT(DISTINCT user_id) as active_traders
           FROM trades
           WHERE date(opened_at) = date('now')"""
    ).fetchone()
    r = dict(row)

    # Win rate
    wins_row = conn.execute(
        "SELECT COUNT(*) as w FROM trades WHERE date(opened_at)=date('now') AND result='WIN'"
    ).fetchone()
    total = r['count'] or 1
    r['win_rate'] = round((wins_row[0] / total) * 100, 1) if total > 0 else 0
    conn.close()
    return r


def get_per_user_today() -> list:
    conn = get_connection()
    rows = conn.execute(
        """SELECT
              u.telegram_username AS username,
              u.iq_user_id,
              u.token,
              COUNT(t.id) AS count,
              COALESCE(SUM(t.amount), 0) AS volume,
              COALESCE(SUM(CASE WHEN t.result='WIN' THEN t.pnl
                           WHEN t.result='LOSS' THEN -t.amount
                           ELSE 0 END), 0) AS pnl
           FROM users u
           JOIN trades t ON t.user_id = u.id
           WHERE date(t.opened_at) = date('now')
           GROUP BY u.id
           ORDER BY pnl DESC
           LIMIT 20"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_trade_by_iq_id(iq_option_id: int) -> Optional[dict]:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM trades WHERE iq_option_id=?", (iq_option_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None
