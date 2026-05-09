"""
Technical indicators used by the bias engine.
RSI(14), EMA(9), EMA(21), MACD(12,26,9)
"""
from typing import List


def compute_rsi(closes: List[float], period: int = 14) -> float:
    """
    Compute RSI for the given closes list.
    Returns 0-100 value. Uses Wilder's smoothing.
    """
    if len(closes) < period + 1:
        return 50.0  # Neutral if insufficient data

    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(d, 0) for d in deltas]
    losses = [max(-d, 0) for d in deltas]

    # Initial average
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    # Wilder's smoothing for remaining
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi


def compute_ema(closes: List[float], period: int) -> list:
    """
    Compute EMA for each position in closes.
    Returns list of same length (first period-1 values are None).
    """
    if len(closes) < period:
        return [None] * len(closes)

    multiplier = 2.0 / (period + 1)
    ema = [None] * len(closes)

    # First EMA is SMA
    ema[period - 1] = sum(closes[:period]) / period

    for i in range(period, len(closes)):
        ema[i] = (closes[i] - ema[i - 1]) * multiplier + ema[i - 1]

    return ema


def compute_macd(
    closes: List[float],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9
) -> tuple:
    """
    Compute MACD line and signal line.
    Returns (macd_line, signal_line) — last value of each.
    """
    ema_fast = compute_ema(closes, fast)
    ema_slow = compute_ema(closes, slow)

    # MACD line = EMAs fast - slow
    macd_line = []
    for f, s in zip(ema_fast, ema_slow):
        if f is not None and s is not None:
            macd_line.append(f - s)
        else:
            macd_line.append(None)

    # Signal line = EMA of MACD line
    valid_macd = [v for v in macd_line if v is not None]
    if len(valid_macd) < signal:
        return (0.0, 0.0)

    signal_ema = compute_ema(valid_macd, signal)
    last_signal = signal_ema[-1]
    if last_signal is None:
        return (0.0, 0.0)
    return (valid_macd[-1], last_signal)
