"""Broadcast model operations."""
from database.db import get_connection


def log_broadcast(
    admin_id: int, target_segment: str, message_text: str,
    sent_count: int = 0, image_path: str = None,
    button_text: str = None, button_url: str = None
) -> int:
    conn = get_connection()
    cursor = conn.execute(
        """INSERT INTO broadcasts
           (admin_id, target_segment, message_text, image_path,
            button_text, button_url, sent_count, sent_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
        (admin_id, target_segment, message_text, image_path,
         button_text, button_url, sent_count)
    )
    conn.commit()
    bid = cursor.lastrowid
    conn.close()
    return bid


def update_broadcast_count(broadcast_id: int, count: int):
    conn = get_connection()
    conn.execute(
        "UPDATE broadcasts SET sent_count=? WHERE id=?", (count, broadcast_id)
    )
    conn.commit()
    conn.close()
