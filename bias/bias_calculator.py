"""
Combines RSI, EMA cross, and MACD into a single bullish bias percentage (0-100).
"""
from bias.indicators import compute_rsi, compute_ema, compute_macd
from typing import Optional


def calculate_bias(candles: list) -> Optional[dict]:
    """
    Takes a list of candles (most recent last), returns bias dict.
    Uses RSI(14), EMA(9 vs 21 cross), MACD(12,26,9) — three independent signals.

    Returns None if insufficient data (< 30 candles).
    """
    if not candles or len(candles) < 30:
        return None

    try:
        closes = [c['close'] for c in candles]
    except (KeyError, TypeError):
        return None

    # 1. RSI score: 0-100, where higher = more bullish
    rsi = compute_rsi(closes, period=14)
    rsi_score = rsi  # already 0-100, 50 = neutral

    # 2. EMA cross score
    ema9_list = compute_ema(closes, 9)
    ema21_list = compute_ema(closes, 21)
    ema9 = ema9_list[-1]
    ema21 = ema21_list[-1]

    if ema9 > ema21:
        diff_pct = abs(ema9 - ema21) / closes[-1] * 100 if closes[-1] else 0
        ema_score = 70 + min(30, diff_pct)
        ema_signal = 'BULL'
    elif ema9 < ema21:
        diff_pct = abs(ema9 - ema21) / closes[-1] * 100 if closes[-1] else 0
        ema_score = 30 - min(30, diff_pct)
        ema_signal = 'BEAR'
    else:
        ema_score = 50
        ema_signal = 'NEUTRAL'

    # 3. MACD score
    macd_line, signal_line = compute_macd(closes)
    if macd_line > signal_line:
        macd_score = 70
        macd_signal = 'BULL'
    elif macd_line < signal_line:
        macd_score = 30
        macd_signal = 'BEAR'
    else:
        macd_score = 50
        macd_signal = 'NEUTRAL'

    # Combined bullish percent — weighted average
    bullish = (rsi_score * 0.4) + (ema_score * 0.35) + (macd_score * 0.25)
    bullish = max(0.0, min(100.0, bullish))

    # Confidence = agreement between indicators
    signals = [
        'BULL' if rsi_score > 55 else ('BEAR' if rsi_score < 45 else 'NEUTRAL'),
        ema_signal,
        macd_signal,
    ]
    bull_count = signals.count('BULL')
    bear_count = signals.count('BEAR')
    confidence = max(bull_count, bear_count) / 3.0 * 100

    return {
        'bullish_percent': round(bullish, 1),
        'bearish_percent': round(100.0 - bullish, 1),
        'confidence': round(confidence, 1),
        'rsi_value': round(rsi, 2),
        'ema_signal': ema_signal,
        'macd_signal': macd_signal,
        'last_close': closes[-1],
        'candles_used': len(candles),
    }
