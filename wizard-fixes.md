# Wizard Fixes — IQ Bot v2

**Date:** 2026-05-10
**Author:** Wizard (Hermes Agent)

---

## Round 4 — Trade Rejection on New Account

### Symptom

New account (`Shilohwrpz@gmail.com`, user 54, profile 176449379) onboarded successfully. Balance syncs ($28.93 practice). But trade fails with:

```
Trade failed: IQ Option returned no trade ID.
Response: {'message': 'Time for purchasing options is over, please try again later.'}
```

### Root Cause

**Not a code bug.** IQ Option rejected the trade with a legitimate market timing error. The asset (EURUSD-OTC, 30s) is not accepting orders — likely the OTC market window closed or the 30-second timeframe isn't available right now.

The watcher correctly:
1. Received the trade request on `trade-requests:54`
2. Connected to IQ Option (profile 176449379, 2 balances, 286 actives)
3. Attempted to place the binary option
4. IQ Option responded with: `{'message': 'Time for purchasing options is over, please try again later.'}`
5. The validation code (from `claude/fix-repo-issues-am3zk`) detected no trade ID and reported the error

### User-Facing Improvement Needed

The error displayed to the user is misleading — "IQ Option returned no trade ID" sounds like a bug. The actual IQ Option error message should be shown instead:

```python
# In watcher/connection.py, the trade ID validation:
if not trade_iq_id:
    error_msg = result.get('message', 'No trade ID returned') if isinstance(result, dict) else 'No trade ID returned'
    await publish(f'trade-results:{self.user_id}', {
        'request_token': req['request_token'],
        'status': 'ERROR',
        'error': error_msg,  # Show actual IQ Option message
    })
```

### Account State

| Field | Old Account (user 2) | New Account (user 54) |
|-------|---------------------|----------------------|
| Email | Shilohx436@gmail.com | Shilohwrpz@gmail.com |
| Profile | 182511307 | 176449379 |
| Practice | $4,379.87 | $28.93 |
| Real | $0.00 | $0.00 |
| Watcher | ✅ Running | ✅ Running |

### Action

- Try a different asset/timeframe that's currently open
- Try during active market hours
- Improve error message to surface IQ Option's actual rejection reason
