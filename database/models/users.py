"""User model operations."""
from database.db import get_connection
from typing import Optional


def upsert_user(telegram_id: int, telegram_username: str = '') -> dict:
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO users (telegram_id, telegram_username, last_active_at)
               VALUES (?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(telegram_id) DO UPDATE SET
                   telegram_username=excluded.telegram_username,
                   last_active_at=CURRENT_TIMESTAMP""",
            (telegram_id, telegram_username)
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM users WHERE telegram_id=?", (telegram_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_user(telegram_id: int) -> Optional[dict]:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM users WHERE telegram_id=?", (telegram_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_user_by_id(user_id: int) -> Optional[dict]:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM users WHERE id=?", (user_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def set_iq_id_verified(telegram_id: int, iq_user_id: int):
    conn = get_connection()
    try:
        conn.execute(
            """UPDATE users SET iq_user_id=?, approval_status='PENDING',
               referrer_check_passed=1
               WHERE telegram_id=?""",
            (iq_user_id, telegram_id)
        )
        conn.commit()
    finally:
        conn.close()


def set_iq_user_id(telegram_id: int, iq_user_id: int):
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE users SET iq_user_id = ? WHERE telegram_id = ?",
            (iq_user_id, telegram_id)
        )
        conn.commit()
    finally:
        conn.close()


def set_referrer_check_passed(telegram_id: int, passed: bool):
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE users SET referrer_check_passed = ? WHERE telegram_id = ?",
            (1 if passed else 0, telegram_id)
        )
        conn.commit()
    finally:
        conn.close()


def set_rejection(telegram_id: int, reason: str):
    conn = get_connection()
    try:
        conn.execute(
            """UPDATE users SET approval_status='REJECTED', rejection_reason=?
               WHERE telegram_id=?""",
            (reason, telegram_id)
        )
        conn.commit()
    finally:
        conn.close()


def approve_user(user_id: int, tier: str = 'NEWBIE'):
    conn = get_connection()
    try:
        conn.execute(
            """UPDATE users SET approval_status='APPROVED', tier=?
               WHERE id=?""",
            (tier, user_id)
        )
        conn.commit()
    finally:
        conn.close()


def set_token(user_id: int, token: str):
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE users SET token=?, approval_status='APPROVED' WHERE id=?",
            (token, user_id)
        )
        conn.commit()
    finally:
        conn.close()


def set_tier(user_id: int, tier: str):
    conn = get_connection()
    try:
        conn.execute("UPDATE users SET tier=? WHERE id=?", (tier, user_id))
        conn.commit()
    finally:
        conn.close()


def get_pending_users() -> list:
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT * FROM users
               WHERE approval_status='PENDING' AND referrer_check_passed=1"""
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def find_user_by_username_or_iq_id(query: str) -> Optional[dict]:
    conn = get_connection()
    try:
        row = conn.execute(
            """SELECT * FROM users
               WHERE telegram_username=? OR CAST(iq_user_id AS TEXT)=?
               OR CAST(telegram_id AS TEXT)=?""",
            (query, query, query)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def find_user_full(query: str) -> Optional[dict]:
    """Find user by IQ Option ID, telegram username (with or without @), or telegram_id."""
    if isinstance(query, str):
        query = query.strip().lstrip('@')
    conn = get_connection()
    try:
        if str(query).isdigit():
            n = int(query)
            row = conn.execute(
                "SELECT * FROM users WHERE iq_user_id = ? OR telegram_id = ?",
                (n, n)
            ).fetchone()
            if row:
                return _enrich_user(dict(row))
        row = conn.execute(
            "SELECT * FROM users WHERE LOWER(telegram_username) = LOWER(?)",
            (query,)
        ).fetchone()
        return _enrich_user(dict(row)) if row else None
    finally:
        conn.close()


def _enrich_user(user: dict) -> dict:
    """Enrich user dict with trade stats."""
    conn = get_connection()
    try:
        row = conn.execute(
            """SELECT
                  COUNT(t.id) as total_trades,
                  COALESCE(SUM(CASE WHEN t.result='WIN' THEN t.pnl
                               WHEN t.result='LOSS' THEN -t.amount
                               ELSE 0 END), 0) as total_pnl,
                  CASE WHEN COUNT(t.id) > 0
                       THEN ROUND(100.0 * SUM(CASE WHEN t.result='WIN' THEN 1 ELSE 0 END)
                                  / COUNT(t.id), 1)
                       ELSE 0 END as win_rate
               FROM trades t WHERE t.user_id = ?""",
            (user['id'],)
        ).fetchone()
        if row:
            user.update(dict(row))
        return user
    finally:
        conn.close()


def get_all_user_ids() -> list:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, telegram_id FROM users WHERE approval_status='APPROVED'"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_pending_token_users() -> list:
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT id, telegram_username, telegram_id, iq_user_id
               FROM users
               WHERE approval_status = 'APPROVED'
                 AND (token IS NULL OR token = '')
                 AND tier != 'BANNED'
               ORDER BY created_at DESC
               LIMIT 50"""
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_active_token_users() -> list:
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT id, telegram_username, telegram_id, iq_user_id, token
               FROM users
               WHERE token IS NOT NULL AND token != ''
                 AND tier != 'BANNED'
               ORDER BY created_at DESC"""
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_users_by_segment(segment: str) -> list:
    conn = get_connection()
    try:
        if segment == 'ALL':
            rows = conn.execute(
                "SELECT telegram_id, telegram_username FROM users "
                "WHERE approval_status = 'APPROVED' AND tier != 'BANNED'"
            ).fetchall()
        elif segment == 'INACTIVE_5H':
            rows = conn.execute(
                "SELECT telegram_id, telegram_username FROM users "
                "WHERE approval_status = 'APPROVED' AND tier != 'BANNED' "
                "AND (last_trade_at IS NULL "
                "     OR last_trade_at < datetime('now', '-5 hours'))"
            ).fetchall()
        elif segment == 'ACTIVE':
            rows = conn.execute(
                "SELECT telegram_id, telegram_username FROM users "
                "WHERE approval_status = 'APPROVED' AND tier != 'BANNED' "
                "AND last_trade_at >= datetime('now', '-5 hours')"
            ).fetchall()
        elif segment in ('NEWBIE', 'PRO'):
            rows = conn.execute(
                "SELECT telegram_id, telegram_username FROM users "
                "WHERE approval_status = 'APPROVED' AND tier = ?",
                (segment,)
            ).fetchall()
        else:
            return []
        return [dict(r) for r in rows]
    finally:
        conn.close()


def log_funnel_event(telegram_id, event_type: str, metadata: str = None):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO funnel_events (telegram_id, event_type, metadata) VALUES (?,?,?)",
            (telegram_id, event_type, metadata)
        )
        conn.commit()
    finally:
        conn.close()
