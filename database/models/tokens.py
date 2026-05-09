"""Token model operations."""
from database.db import get_connection
from typing import Optional


def assign_token(user_id: int, token: str) -> bool:
    """Assign a token to a user (admin action)."""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE users SET token=? WHERE id=?", (token, user_id)
        )
        conn.commit()
        return True
    except Exception:
        return False
    finally:
        conn.close()


def revoke_token(token: str) -> bool:
    conn = get_connection()
    conn.execute(
        "UPDATE users SET token=NULL WHERE token=?", (token,)
    )
    conn.commit()
    conn.close()
    return True


def validate_token(telegram_id: int, token: str) -> bool:
    conn = get_connection()
    row = conn.execute(
        "SELECT 1 FROM users WHERE telegram_id=? AND token=?", (telegram_id, token)
    ).fetchone()
    conn.close()
    return row is not None
