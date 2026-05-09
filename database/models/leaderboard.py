"""
Leaderboard model operations.
"""
from database.db import get_connection


def get_leaderboard(period: str = 'ALL_TIME', limit: int = 10) -> list:
    conn = get_connection()
    rows = conn.execute(
        """SELECT * FROM leaderboard
           WHERE period = ?
           ORDER BY rank
           LIMIT ?""",
        (period, limit)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_top_real_traders(limit: int = 10) -> list:
    conn = get_connection()
    rows = conn.execute(
        """SELECT
              u.telegram_username,
              u.iq_user_id,
              COUNT(t.id) as count,
              COALESCE(SUM(CASE WHEN t.result='WIN' THEN t.pnl
                           WHEN t.result='LOSS' THEN -t.amount
                           ELSE 0 END), 0) as pnl
           FROM users u
           JOIN trades t ON t.user_id = u.id
           WHERE t.result IS NOT NULL
           GROUP BY u.id
           ORDER BY pnl DESC
           LIMIT ?""",
        (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_leaderboard_entry(rank: int, display_name: str, profit: float,
                          currency: str, period: str, admin_id: int):
    conn = get_connection()
    conn.execute(
        """INSERT INTO leaderboard
           (rank, display_name, profit_amount, profit_currency,
            period, updated_by_admin)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (rank, display_name, profit, currency, period, admin_id)
    )
    conn.commit()
    conn.close()


def clear_leaderboard(period: str = None):
    conn = get_connection()
    if period:
        conn.execute("DELETE FROM leaderboard WHERE period = ?", (period,))
    else:
        conn.execute("DELETE FROM leaderboard")
    conn.commit()
    conn.close()


def publish_real_top_to_leaderboard(admin_id: int, period: str = 'ALL_TIME', limit: int = 10):
    real = get_top_real_traders(limit=limit)
    conn = get_connection()
    try:
        conn.execute("DELETE FROM leaderboard WHERE period = ?", (period,))
        for i, t in enumerate(real, 1):
            name = f"@{t['telegram_username']}" if t['telegram_username'] else f"Trader#{t['iq_user_id']}"
            conn.execute(
                """INSERT INTO leaderboard
                   (rank, display_name, profit_amount, profit_currency, period, updated_by_admin)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (i, name, t['pnl'], 'USD', period, admin_id)
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return len(real)
