"""Funnel event model operations."""
from database.db import get_connection


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


def get_funnel_stats(days: int = 7) -> dict:
    conn = get_connection()
    try:
        row = conn.execute(
            """SELECT
                  COUNT(*) as total,
                  SUM(CASE WHEN event_type='LANDING_VIEW' THEN 1 ELSE 0 END) as landing_views,
                  SUM(CASE WHEN event_type='LANDING_CLICK' THEN 1 ELSE 0 END) as landing_clicks,
                  SUM(CASE WHEN event_type='STARTED' THEN 1 ELSE 0 END) as started,
                  SUM(CASE WHEN event_type='VERIFIED' THEN 1 ELSE 0 END) as verified,
                  SUM(CASE WHEN event_type='FIRST_TRADE' THEN 1 ELSE 0 END) as first_trade
               FROM funnel_events
               WHERE date(created_at) >= date('now', ?)""",
            (f'-{days} days',)
        ).fetchone()
        return dict(row) if row else {}
    finally:
        conn.close()
