"""Pending trade result tracking — written before wait loop, deleted on resolution."""
import time
from database.db import get_connection


def save_pending(
    user_id: int, account_id: int, iq_option_id: int,
    pair: str, direction: str, amount: float,
    duration_seconds: int, balance_type: str, expires_at: int,
):
    conn = get_connection()
    try:
        conn.execute(
            """INSERT OR IGNORE INTO pending_results
               (user_id, account_id, iq_option_id, pair, direction,
                amount, duration_seconds, balance_type, expires_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (user_id, account_id, iq_option_id, pair, direction,
             amount, duration_seconds, balance_type, expires_at),
        )
        conn.commit()
    finally:
        conn.close()


def delete_pending(iq_option_id: int):
    conn = get_connection()
    try:
        conn.execute("DELETE FROM pending_results WHERE iq_option_id=?", (iq_option_id,))
        conn.commit()
    finally:
        conn.close()


def get_stale_pending(grace_seconds: int = 120) -> list:
    """Return pending trades whose option has expired (+ grace period)."""
    cutoff = int(time.time()) - grace_seconds
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM pending_results WHERE expires_at < ?", (cutoff,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
