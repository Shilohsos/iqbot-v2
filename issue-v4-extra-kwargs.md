# V4 Merge Bug: trade.py passes extra kwargs to execute_trade()

**Date:** 2026-05-10
**Branch:** master (V4 hybrid merge)

## Error

```
TypeError: execute_trade() got an unexpected keyword argument 'user_id'
```

## Root Cause

`core/trade_executor.py` V4 signature:
```python
async def execute_trade(
    ssid, platform_id, pair, direction, amount,
    duration_seconds, balance_type='PRACTICE'
)
```

`bot/handlers/trade.py` call site still passes V3 kwargs:
```python
result = await execute_trade(
    ssid=fresh_ssid,
    platform_id=account['platform_id'],
    pair=pair,
    direction=direction,
    amount=amount,
    duration_seconds=tf,
    balance_type=balance_type,
    user_id=user['id'],        # ❌ not in V4
    account_id=account['id'],   # ❌ not in V4
)
```

## Fix

Remove `user_id` and `account_id` from the call site at `bot/handlers/trade.py` line 416-417.

Also in `_run_martingale()` around line 112-120 (same call pattern).
