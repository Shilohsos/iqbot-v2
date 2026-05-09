"""Market bias model operations."""
from database.db import get_connection
from typing import Optional


def upsert_bias(
    asset: str,
    timeframe_seconds: int,
    bullish_percent: float,
    bearish_percent: float,
    confidence: float,
    rsi_value: float = None,
    ema_signal: str = None,
    macd_signal: str = None,
    last_close: float = None,
    candles_used: int = None,
    is_suspended: bool = False,
):
    conn = get_connection()
    try:
        conn.execute(
            """INSERT OR REPLACE INTO market_bias
               (asset, timeframe_seconds, bullish_percent, bearish_percent,
                confidence, rsi_value, ema_signal, macd_signal, last_close,
                candles_used, is_suspended, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
            (asset, timeframe_seconds, bullish_percent, bearish_percent,
             confidence, rsi_value, ema_signal, macd_signal, last_close,
             candles_used, 1 if is_suspended else 0)
        )
        conn.commit()
    finally:
        conn.close()


def get_current_bias(pair: str, timeframe_seconds: int) -> Optional[dict]:
    conn = get_connection()
    try:
        row = conn.execute(
            """SELECT * FROM market_bias
               WHERE asset=? AND timeframe_seconds=?
               ORDER BY updated_at DESC LIMIT 1""",
            (pair, timeframe_seconds)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_top_pairs_by_confidence(
    timeframe: int = 300,
    limit: int = 8
) -> list:
    conn = get_connection()
    rows = conn.execute(
        """SELECT * FROM market_bias
           WHERE timeframe_seconds=? AND is_suspended=0
           ORDER BY confidence DESC
           LIMIT ?""",
        (timeframe, limit)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
