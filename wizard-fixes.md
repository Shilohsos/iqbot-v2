# Wizard Fixes — IQ Bot v2

**Date:** 2026-05-10
**Author:** Wizard (Hermes Agent)

---

## Round 3 — Balance & Bias Engine Issues (ACTIVE)

### Issue #1: Live Balance Shows $0.00

**Symptom:** Telegram `/balance` shows Practice: $4,379.87 but Live: $0.00

**DB state:**
```
user_id=2, practice_balance_amount=4379.87, real_balance_amount=0.0
```

**Watcher confirms 2 balances exist:**
```
07:56:48 Client ready. 2 balances, 286 actives
07:56:48 Sent balance subscription bal_id=1223061988
07:56:48 Sent balance subscription bal_id=1223061989
```

**Earlier watcher run (00:27:16) confirmed real balance exists:**
```
balance_sync: {"balance_type":1, "amount":4379.87}
balance_sync: {"balance_type":4, "amount":8182.71}
```

**Root cause hypothesis:** The `update_balance()` function in `database/models/accounts.py` maps `balance_type == 1` to `real_balance_amount` and anything else to `practice_balance_amount`. But IQ Option may return different type values than expected, OR the watcher's `start()` loop is not calling `update_balance()` for both balance objects correctly.

**Files to investigate:**
- `database/models/accounts.py` — `update_balance()` (line 60)
- `watcher/connection.py` — balance sync loop (lines 46-52)
- `core/iq_client.py` — `_refresh_balances()` (line 117) — check what `bal['type']` values actually are

---

### Issue #2: Bias Engine Shows UNKNOWN

**Symptom:** Telegram `/system` shows "Bias engine: UNKNOWN" even though `pm2 list` shows `iqbot-v2-bias` is ONLINE.

**Root cause:** `bot/admin/system.py` still references PM2 process name `iqbot-v2-bias-engine` (lines 54, 99, 104), but the actual PM2 process is named `iqbot-v2-bias`.

```python
# system.py line 54 — WRONG NAME:
bias_status = pm2_status('iqbot-v2-bias-engine')

# Should be:
bias_status = pm2_status('iqbot-v2-bias')
```

**This fix was previously applied but LOST during the merge conflict resolution** of PR #4 (`df072b4`). The `git checkout --theirs` resolved the conflict by using the PR branch version which had the old name.

**Fix:** Change all 3 occurrences of `iqbot-v2-bias-engine` to `iqbot-v2-bias` in `bot/admin/system.py`.

---

## Previous Rounds (RESOLVED)

### Round 2 — Trade Failures (Resolved by PR #4)

All three fixes applied in `d9a7d2d`:
1. ✅ `core/iq_client.py` — `self.connected = True` moved to after all init steps
2. ✅ `watcher/connection.py` — `_subscribe_streams()` + `on_reconnect` for subscription replay
3. ✅ `watcher/connection.py` — Pre-trade connection guard

### Round 1 — Bot Crash Loop (Resolved)

1. ✅ `ecosystem.config.js` — `restart_delay: 8000` + `kill_timeout: 10000`
2. ✅ Missing pip packages installed
