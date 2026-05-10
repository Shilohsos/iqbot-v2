# CRITICAL: Trade Results Never Arrive — Root Cause Found

**Date:** 2026-05-10  
**Reporter:** Wizard  
**Branch:** master (post fix-trade-results merge)

---

## Root Cause

The bot subscribes to position updates using the **wrong IQ Option protocol call**.  
Position-changed events never arrive because the subscription format is incorrect.

### What the bot sends (WRONG):

```json
{
  "name": "sendMessage",
  "msg": {
    "name": "portfolio.subscribe-positions",
    "version": "1.0",
    "body": {"frequency": "realtime", "ids": []}
  }
}
```

### What the IQ Option SDK sends (CORRECT):

```json
{
  "name": "subscribeMessage",
  "msg": {
    "name": "portfolio.position-changed",
    "version": "3.0",
    "params": {
      "routingFilters": {"user_id": <IQ_USER_ID>}
    }
  }
}
```

### Differences:

| Field | Bot (wrong) | SDK (correct) |
|---|---|---|
| Frame type | `sendMessage` | `subscribeMessage` |
| Event name | `portfolio.subscribe-positions` | `portfolio.position-changed` |
| Version | `1.0` | `3.0` |
| Params key | `body` | `params` |
| Filter | `frequency` + `ids` | `routingFilters.user_id` |

Also missing: `user_id` — the IQ Option profile user ID (not Telegram ID). This must be fetched from the `core.get-profile` response (field: `id` or `user_id`).

---

## Evidence

PM2 logs from the latest trade (id=13884153307) show the result loop receiving **only** `timeSync` messages — zero `position-changed` events. The subscription never activated, so IQ Option never sends position data.

```
16:54:44 Result loop unmatched: name='timeSync' trade_id=13884153307
16:54:45 Result loop unmatched: name='timeSync' trade_id=13884153307
... (repeated for 60+ seconds until timeout)
```

---

## Required Changes

1. **`core/iq_protocol.py`** — Add new function:
   ```python
   def msg_subscribe_position_changed(user_id: int, request_id: str) -> str
   ```
   That sends the correct `subscribeMessage` frame with `portfolio.position-changed` v3.0.

2. **`core/trade_executor.py`** — In `_connect_and_init()` or in `execute_trade()`:
   - After `msg_get_profile`, extract `user_id` from the profile response
   - Call `msg_subscribe_position_changed(user_id)` with a `subscribeMessage` frame
   - Wait for ACK before placing trade

3. The existing `msg_subscribe_position_state` can remain but is NOT sufficient for receiving trade results.

---

**Reference:** `client-sdk-js` → `SubscribePortfolioPositionChangedV3` (line 10557 of `iq-pass/src/index.ts`)
