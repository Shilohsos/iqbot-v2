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

**Fix:** Move `return status.upper()` inside the `if` block.

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

### 🟡 #7 — "Find Users" Admin Button Does Not Work

**Root Cause:** When admin clicks "Find Users" from the admin panel, the callback
`adm:find_user_prompt` routes to `cmd_find()` with empty `ctx.args`. The function
shows the prompt text but does **not** set `ctx.user_data['awaiting_find_query'] = True`.

The text router in `main_bot.py` only routes typed text to `msg_find_query` if
`awaiting_find_query` is set:

```python
# main_bot.py — text_router
if ctx.user_data.get('awaiting_find_query'):
    from bot.admin.find_users import msg_find_query
    await msg_find_query(update, ctx)
    return
```

Since the flag is never set, typing a username after clicking the button is
ignored. Only `/find <query>` (command with args) works.

**Fix:** Add `ctx.user_data['awaiting_find_query'] = True` in `cmd_find()` when
`ctx.args` is empty and the function is showing the prompt.

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
| 7 | "Find Users" button broken | Clicking it doesn't set `awaiting_find_query` | Can't search by typing, only `/find` works |

---

## Issue Identified (from audit branch)

The `market_bias` table needs a new column (`is_suspended`) that was added to
`database/db.py` so the bias engine can mark suspended assets and prevent them
from appearing in the trade pair selection keyboard.

Without the column, `upsert_bias()` attempts to write 12 values into an
11-column table, causing the bias engine to crash on the first candle close:

```
OperationalError: table market_bias has 11 columns but 12 values were supplied
```

## Fix Implemented — Automatic Migration in `init_db()`

**No manual SQL is required.** The fix is already applied in `database/db.py`.
`init_db()` now runs a safe migration at every startup:

```python
# In database/db.py → init_db()
cols = {row[1] for row in conn.execute("PRAGMA table_info(market_bias)")}
if 'is_suspended' not in cols:
    conn.execute(
        "ALTER TABLE market_bias ADD COLUMN is_suspended INTEGER NOT NULL DEFAULT 0"
    )
conn.commit()
```

This uses SQLite's `PRAGMA table_info` to detect whether the column already
exists before running `ALTER TABLE`, so it is safe to call on both new and
existing databases without error.

## How to Verify

After restarting the bot (which calls `init_db()` at startup), run:

```sql
PRAGMA table_info(market_bias);
```

The output must include a row with `name = is_suspended`, `type = INTEGER`,
`notnull = 1`, and `dflt_value = 0`.

## Related Changes in This Audit Branch

All changes below are committed to `claude/review-github-files-TyJZA`:

| Area | Change |
|------|--------|
| `database/db.py` | Added `is_suspended` to `market_bias` schema + automatic `ALTER TABLE` migration in `init_db()` |
| `database/models/bias.py` | `upsert_bias()` accepts `is_suspended` kwarg; `get_top_pairs_by_confidence()` filters out suspended pairs |
| `bias/engine.py` | Reads `client.actives[active_id]['is_suspended']` and passes it to `upsert_bias()` on every candle close |
| `core/iq_client.py` | Fixed double `_receive_loop` spawn on reconnect; fixed future leak on timeout; clears `actives` before refresh |
| `watcher/connection.py` | Trade listener now auto-restarts with exponential backoff instead of dying silently |
| `bot/handlers/start.py` | Fixed broken `log_funnel_event` import (moved to `database.models.funnel`) |
| `bot/handlers/onboard.py` | Same import fix; wired `spawn_watcher(user_id)` so approved users get a live watcher process |
| `bot/handlers/verify.py` | Same import fix |
| `core/iq_protocol.py` | `gen_request_id()` uses full 128-bit UUID instead of truncated 64-bit |
| `bot/admin/system.py` | Fixed PM2 process name (`iqbot-v2-bias-engine`); real Redis ping; `db_size` uses config path |
| `database/models/leaderboard.py` | Added `try/finally` to all 4 connection-using functions |
| `bot/ui/messages.py` | Added `md_escape()` helper for untrusted text in Markdown contexts |
| `requirements.txt` / `database/db.py` | Removed unused `aiosqlite` dependency (only sync `sqlite3` is used) |
