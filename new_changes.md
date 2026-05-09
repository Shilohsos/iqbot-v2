# IQBot v2 — Root Cause Diagnostic Report

## Verified Issues (May 9, 2026 — 23:50 WAT)

---

### 🔴 #1 — System Panel Shows UNKNOWN for All Processes

**Root Cause:** `bot/admin/system.py` — the `pm2_status()` function has a bug at the
`return` statement placement. It returns on the **first** iteration of the `for` loop,
before `status` has been assigned (unless the first PM2 process happens to match).

```python
def pm2_status(name):
    try:
        r = subprocess.run(['pm2', 'jlist'], ...)
        procs = json.loads(r.stdout)
        for p in procs:
            if p.get('name') == name:
                status = p.get('pm2_env', {}).get('status') or 'unknown'
            return status.upper()  # ← RETURNS ON FIRST ITERATION
    except Exception:
        pass
    return 'UNKNOWN'
```

The first PM2 process is `iqbot-bot` (id=0, status=stopped). It doesn't match
`iqbot-v2-bot` or `iqbot-v2-bias-engine`, so `status` is never assigned. Python
throws `NameError: cannot access local variable 'status'`, caught by the blank
`except`, returning `'UNKNOWN'`.

**Fix:** Move `return status.upper()` **outside** the for loop (after it, at the
same indentation level as `for`). Also initialize `status = None` before the loop.

---

### 🔴 #2 — Trades Never Execute (Admin-Watcher Mismatch)

**Root Cause:** The admin user (telegram_id=1615652240, @shiloh_is_10xing) has
`DB user_id=1`. The PM2 watcher is running for `user_id=2` (@abijahtega).

```
Bot trade flow:     publish → trade-requests:1
Watcher listening:  subscribe → trade-requests:2
                              ↑ NEVER MATCHES
```

Trade requests go to Redis channel 1 but no process subscribes to that channel.
The trade stays PENDING forever.

**Secondary cause:** User DB id=1 has **no account** in the `accounts` table.
Only user_id=2 has an account (acct_id=1). The admin was auto-approved (tier=ADMIN)
and never went through `/addaccount`, so no credentials exist for them.

---

### 🔴 #3 — Bot Allows Trading Without a Linked Account

**Root Cause:** `bot/handlers/trade.py` → `cb_confirm_trade()` calls
`get_user_account_summary(user['id'])` which returns default zeros when no
account exists:

```python
return {
    'practice_balance': 0, 'practice_currency': 'USD',
    'real_balance': 0, 'real_currency': 'USD',
}
```

The bot does **not** check if the user has a linked account before allowing
the trade. It publishes to Redis regardless, creating orphaned trade requests
with no watcher to consume them.

---

### 🟡 #4 — Balance Shows Wrong Amount

**Root Cause:** The practice balance in the DB (`$4,371.87`) was synced whenever
the watcher last connected and received a balance-changed event. But:

1. The admin (user_id=1) sees `$0.00` because they have no account entry
2. User 2 sees `$4,371.87` regardless of the actual IQ Option balance

The watcher subscribes to `marginal-portfolio.subscribe-balance-changed` via
raw WebSocket (not through the `_request` pattern) — if the subscription silently
fails or events stop flowing, the balance stays stale forever.

---

### 🟡 #5 — Pending Trades Never Transition to WIN/LOSS

**Root Cause:** The watcher subscribes to position-changed events via raw WS
(`msg_subscribe_position_state`), again without the `_request`/future pattern.
The `_handle_position` method waits for `status='closed'` to call
`update_trade_result` and publish `CLOSED` to Redis.

But since no trade is ever actually placed (see #2), position-changed events
with matching `external_id` values never arrive. The bot either times out
or never gets a CLOSED event, leaving trades in PENDING state.

---

### 🟡 #6 — Balance Syncing Dependent on WS Events Only

**Root Cause:** `watcher/connection.py` syncs balances to DB only when:

1. Initial connection — `update_balance()` called once for each balance
2. `balance-changed` WS event fires

There is no periodic polling or refresh. If the balance changes but the event
is dropped, the DB stays stale. The bot reads balance from the DB, not from
the live connection.

---

## Summary

| # | Symptom | Root Cause | Impact |
|---|---------|-----------|--------|
| 1 | System panel shows UNKNOWN | `pm2_status()` returns on first loop iteration | Admin can't see process health |
| 2 | Trades never execute | Admin → channel 1, watcher → channel 2 | All trades stay PENDING |
| 3 | Bot allows trading w/o account | No `get_account_credentials` check before trade | Orphaned Redis messages |
| 4 | Balance shows wrong amount | Admin has no account; stale DB for user 2 | Misleading UI |
| 5 | No trade results | No position-changed events (trades never opened) | /history shows PENDING |
| 6 | Balance never refreshes | Only WS push, no polling fallback | Stale balance data |
