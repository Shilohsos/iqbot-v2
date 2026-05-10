# Wizard Fixes — IQ Bot v2

**Date:** 2026-05-10
**Author:** Wizard (Hermes Agent)

---

## Round 5 — V3 Trade Executor: "Time for purchasing options is over"

### Status

V3 one-shot executor deployed and functional. Bot connects, authenticates, resolves pair, places trade. But IQ Option rejects with:

> Time for purchasing options is over, please try again later.

### Debug Evidence

```
15:02:01 DEBUG trade params:
  pair=front.EURUSD-OTC
  active_id=76
  direction=put
  expired_at=1778418151 (now=1778418121, +30s ✓)
  amount=10.0
  balance_id=1223061989 (PRACTICE, $4,379.87)
  profit=86%
  option_type=3 (turbo)
```

All parameters appear correct:
- ✅ Expiry is 30 seconds in the future
- ✅ Active ID resolves from init data
- ✅ Balance ID matches the account's practice balance
- ✅ Profit percent from IQ Option's own commission data
- ✅ Option type 3 for ≤5min turbo

### What's Ruled Out

- ❌ Server clock — matches real time
- ❌ SSID — authenticates successfully
- ❌ Balance — exists and has funds
- ❌ Active ID resolution — resolves to 76
- ❌ Market hours — user confirms manual trades work on same asset/timeframe

### Hypothesis

IQ Option may require a **minimum session warm-up time** between authentication and trade placement on a fresh WebSocket connection. The old persistent watcher model kept the connection alive, so trades were always on a "warm" session. The V3 one-shot executor creates a brand-new connection per trade, which may trigger a different rate-limit or session-validation rule.

Or: the `profit_percent` value (86) may not match IQ Option's expected value for this specific active/option-type combination. The `_get_profit_percent` function extracts commission from init data, but the field path may be wrong for turbo options.

### Recommendation

1. Add a 2-3 second delay after setOptions before placing the trade
2. Verify the profit_percent extraction path for turbo actives
3. Try with option_type_id=1 (binary) instead of 3 (turbo) for 30s trades
4. Fallback: if the error persists, have Claude trace the exact IQ Option API expectations for the "open-option" endpoint
