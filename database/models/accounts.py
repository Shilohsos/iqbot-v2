"""Account model operations."""
from database.db import get_connection
from typing import Optional


def add_account(
    user_id: int, email_encrypted: str, password_encrypted: str,
    ssid: str, platform_id: int
) -> int:
    conn = get_connection()
    cursor = conn.execute(
        """INSERT INTO accounts
           (user_id, email_encrypted, password_encrypted, ssid, ssid_at, platform_id)
           VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, ?)""",
        (user_id, email_encrypted, password_encrypted, ssid, platform_id)
    )
    conn.commit()
    acc_id = cursor.lastrowid
    conn.close()
    return acc_id


def get_account_credentials(user_id: int) -> Optional[dict]:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM accounts WHERE user_id=? AND is_active=1",
        (user_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_user_account_summary(user_id: int) -> dict:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM accounts WHERE user_id=? AND is_active=1",
        (user_id,)
    ).fetchone()
    conn.close()
    if not row:
        return {
            'practice_balance': 0, 'practice_currency': 'USD',
            'real_balance': 0, 'real_currency': 'USD',
        }
    r = dict(row)
    return {
        'practice_balance': r.get('practice_balance_amount', 0),
        'practice_currency': r.get('practice_balance_currency', 'USD'),
        'real_balance': r.get('real_balance_amount', 0),
        'real_currency': r.get('real_balance_currency', 'USD'),
    }


def update_balance(user_id: int, balance_id: int, amount: float, currency: str = 'USD'):
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM accounts WHERE user_id=? AND is_active=1", (user_id,)
    ).fetchone()
    if not row:
        conn.close()
        return
    r = dict(row)
    if balance_id == r.get('real_balance_id'):
        conn.execute(
            """UPDATE accounts
               SET real_balance_amount=?, real_balance_currency=?
               WHERE user_id=? AND is_active=1""",
            (amount, currency, user_id)
        )
    else:
        conn.execute(
            """UPDATE accounts
               SET practice_balance_amount=?, practice_balance_currency=?
               WHERE user_id=? AND is_active=1""",
            (amount, currency, user_id)
        )
    conn.commit()
    conn.close()


def deactivate_account(user_id: int):
    conn = get_connection()
    conn.execute(
        "UPDATE accounts SET is_active=0 WHERE user_id=?", (user_id,)
    )
    conn.commit()
    conn.close()


def update_ssid(account_id: int, ssid: str):
    conn = get_connection()
    conn.execute(
        "UPDATE accounts SET ssid = ?, ssid_at = CURRENT_TIMESTAMP WHERE id = ?",
        (ssid, account_id)
    )
    conn.commit()
    conn.close()


def get_account_by_id(account_id: int) -> Optional[dict]:
    conn = get_connection()
    row = conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
    conn.close()
    return dict(row) if row else None
