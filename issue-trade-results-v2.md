# Issue: Trade Results Not Delivering + Bot Hangs

**Date:** 2026-05-10  
**Reporter:** Wizard  
**Branch:** master (commit dd51e31 merged)

---

## Symptom 1: Trade placed but result unknown

Users see "⚠️ Trade placed but result unknown. Check /history shortly." on every trade. No WIN/LOSS/TIE results ever delivered.

### Evidence (PM2 logs)

```
16:09:19 Trade placed id=13884051640 pair=front.AUDUSD-OTC dir=put amount=10.0
16:11:51 Trade placed id=13884056681 pair=front.EURUSD-OTC dir=put amount=50.0
16:14:34 Trade placed id=13884062692 pair=front.AUDJPY-OTC dir=put amount=50.0
16:29:00 Trade placed id=13884094009 pair=front.EURUSD-OTC dir=put amount=50.0
```

No subsequent "result received", "WIN", "LOSS", "TIE", or "TIMEOUT" log entry for any of these trades.

### Root Cause

`core/trade_executor.py`'s result loop (lines 129–206) waits up to `duration_seconds + 60` (e.g., 120s) for `position-changed` or `socket-option-closed` WebSocket events. When the bot crashes or is restarted during this wait, the in-progress asyncio task is killed. The trade was already placed on IQ Option — it resolves — but the result is silently lost.

The `TIMEOUT` branch (line 201–206) never fires because the asyncio task itself is cancelled by process termination before the timeout expires.

### Recommended Fix

1. **Persist the in-flight trade to DB before waiting.** Write `trade_id`, `user_id`, `pair`, `expiry` to a `pending_results` table immediately after placement (after line 127).
2. **On bot startup, poll IQ Option for pending trade results.** Query the IQ Option API (or a fresh WS connection) for any trades in `pending_results` whose expiry has passed. Close them out.
3. **Timeout should always fire.** If the wait loop is interrupted by cancellation, the `finally` block or a `CancelledError` handler should still return `{"status": "TIMEOUT", ...}`.

---

## Symptom 2: Bot hangs / unresponsive for minutes

User reports: multiple `/addaccount`, `/start`, `/trade` commands sent at 15:28–15:33 but no response for minutes.

### Evidence

```
15:32:16 execute_trade error: 'bool' object has no attribute 'get'
```

This crash kills the bot. PM2 restarts it. During restart, Telegram queues incoming updates, which are processed in bulk after the bot comes back online — appearing as a delayed flood.

### Root Cause

Two crash vectors:
1. **`'bool' object has no attribute 'get'`** (now fixed in dd51e31 — `_wait_for` now normalizes bool responses)
2. **`telegram.error.BadRequest: Message is not modified`** — the `cb_refresh_balance` handler calls `edit_message_text()` with identical content when balance hasn't changed. Telegram rejects it. This is an unhandled exception that crashes the handler (and potentially the bot depending on error handler config).

### Recommended Fix

In `bot/handlers/balance.py`, `cb_refresh_balance`: wrap `edit_message_text` in a try/except for `BadRequest` with "not modified" — just `answer()` the callback silently if nothing changed. Optionally add a timestamp note like "Last checked: 16:11" so the message always differs.

---

## Symptom 3: Refresh button spams errors

Clicking "🔄 Refresh" on the balance screen produces:

```
telegram.error.BadRequest: Message is not modified: specified new message content and reply markup are exactly the same
```

Three back-to-back identical exceptions per click (one per callback query retry).

### Root Cause

`cb_refresh_balance` fetches balance, formats the message, calls `edit_message_text`. If balance hasn't changed since last fetch, the message text and keyboard are byte-identical to the existing message. Telegram rejects the edit.

### Recommended Fix

Same as Symptom 2 — catch `BadRequest` with "not modified" and respond with `callback_query.answer("Balance unchanged")` instead.

---

## Action

Claude: please implement fixes for all three symptoms and push a PR to `claude/fix-trade-results`.
