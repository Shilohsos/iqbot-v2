# Wizard Fixes — IQ Bot v2

**Date:** 2026-05-10
**Author:** Wizard (Hermes Agent)

---

## Current State

**Merged to master (commit `96e0d9b`):**
- ✅ `claude/review-github-files-TyJZA` — bias UNKNOWN + balance fixes (partial)
- ✅ `claude/fix-repo-issues-am3zk` — trade execution, result ID, tier timeframes

**Status after restart:**

| Fix | Status | Detail |
|-----|--------|--------|
| Bias engine UNKNOWN | ✅ Fixed | PM2 name `iqbot-v2-bias` |
| Live balance $0.00 | ❌ Still broken | See below |
| Trade result ID validation | ✅ Applied | |
| Tier timeframes | ✅ Applied | |
| NO_BIAS UX | ✅ Applied | |

---

## Remaining Issue: Live Balance $0.00

**Root cause gap:**

The `update_balance()` function now matches `balance_id` against `real_balance_id` column:

```python
if balance_id == r.get('real_balance_id'):
    # update real_balance_amount
else:
    # update practice_balance_amount
```

But `real_balance_id` and `practice_balance_id` are **NULL** for all accounts:

```
user=2 real_bid=NULL practice_bid=NULL real_amt=$0.0 practice_amt=$4379.87
```

Since NULL never equals any balance_id, every balance update goes to `practice_balance_amount`.

**Fix needed:** During watcher initialization (after `connect()`), the watcher must identify which balance is real vs practice by their `type` field (1=Real, 4=Practice) and store the balance IDs in the accounts table:

```python
# In watcher/connection.py start():
for bal_id, bal in self.client.balances.items():
    if bal.get('type') == 1:  # REAL
        store_real_balance_id(user_id, bal_id)
    elif bal.get('type') == 4:  # PRACTICE
        store_practice_balance_id(user_id, bal_id)
    update_balance(user_id, bal_id, bal['amount'], bal.get('currency', 'USD'))
```

Or alternatively, add a fallback in `update_balance()`: if `real_balance_id` is NULL, use `balance_type` (1 vs 4) to determine which column to update.
