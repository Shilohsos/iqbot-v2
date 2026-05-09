"""
Affiliate verification — checks if IQ user ID exists in affiliate_events.
"""
from database.db import get_connection


async def verify_iq_user_id(iq_user_id: int) -> bool:
    """
    Returns True if iq_user_id was found in the affiliate channel.
    """
    conn = get_connection()
    row = conn.execute(
        "SELECT 1 FROM affiliate_events WHERE iq_user_id = ?",
        (iq_user_id,)
    ).fetchone()
    conn.close()
    return row is not None
