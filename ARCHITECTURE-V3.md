# ARCHITECTURE V3 — One-Shot Trade Execution

**Date:** 2026-05-10
**Author:** Wizard (Hermes Agent)
**Status:** SPECIFICATION — Awaiting Claude Implementation

---

## 1. Problem Statement

The current V2 architecture uses **persistent per-user watcher processes** connected to IQ Option via WebSocket. This model is fundamentally wrong for a **manual trading bot** where every trade is user-initiated via Telegram button click.

**Symptoms of the broken architecture:**
- Watchers crash, enter restart loops, or sit dead for hours
- WebSocket reconnection fails silently, subscriptions are lost
- SSID/acquisition grabs wrong account, balances mismatch
- Trade rejections with opaque IQ Option errors
- Every fix patches a symptom; the architecture itself is the root cause

**Core insight:** A watcher that stays alive 24/7 to occasionally execute a user-clicked trade is like leaving your car engine running all week for a 5-minute drive. It introduces state, fragility, and failure modes with zero benefit.

---

## 2. New Architecture: One-Shot Trade Execution

### 2.1 Overview

No persistent watchers. Every trade is a **self-contained connection cycle:**

```
User clicks /trade on Telegram
       │
       ▼
Bot reads bias from DB
       │
       ▼
Bot calls execute_trade(ssid, platform_id, pair, direction, amount, duration)
       │
       ▼
┌──────────────────────────────────────────┐
│ 1. Connect to IQ Option WebSocket        │
│ 2. Authenticate                          │
│ 3. Send setOptions                       │
│ 4. Fetch balances (pick correct one)     │
│ 5. Place binary option                   │
│ 6. Wait for position-changed event       │
│ 7. Return result (WIN/LOSS/TIE)          │
│ 8. Disconnect                            │
└──────────────────────────────────────────┘
       │
       ▼
Bot displays result to user
```

### 2.2 Trade Lifecycle

```
┌─────────┐     ┌──────────────┐     ┌─────────────┐     ┌──────────┐
│ Telegram │────▶│  Bot Handler │────▶│   Executor   │────▶│ IQ Option│
│  Button  │     │  (trade.py)  │     │ (new module) │     │    WS    │
└─────────┘     └──────────────┘     └─────────────┘     └──────────┘
                      │                      │
                      ▼                      ▼
               ┌────────────┐        ┌──────────────┐
               │  Bias DB   │        │  Trade Result │
               │  (read)    │        │  (WIN/LOSS)   │
               └────────────┘        └──────────────┘
```

**Sequence:**
1. User selects pair → timeframe → amount → confirms
2. Bot handler (`bot/handlers/trade.py`) reads bias from `market_bias` table
3. If bias is neutral or missing → return UX message immediately (no WS connection)
4. If bias has direction → call `execute_trade()`
5. `execute_trade()` returns result dict: `{status: 'WIN'|'LOSS'|'TIE', pnl: float, trade_id: str}`
6. Bot displays result image + caption

### 2.3 Timeout and Error Handling

| Scenario | Timeout | Behavior |
|----------|---------|----------|
| WS connect | 10s | Return "Connection failed" |
| Auth | 10s | Return "Authentication failed" |
| Trade placement | 10s | Return IQ Option error message |
| Waiting for result | duration + 60s | Return "Trade result delayed — check /history" |
| Any exception | — | Return error message, ensure WS is closed |

**Critical:** Every code path must close the WebSocket. Use `try/finally` to guarantee cleanup.

---

## 3. What Gets Removed

### 3.1 Files to Delete
| File | Reason |
|------|--------|
| `watcher/connection.py` | Per-user watcher — replaced by one-shot executor |
| `main_watcher.py` | Watcher entry point — no longer needed |
| `utils/pm2_manager.py` | Dynamic watcher spawning — no longer needed |

### 3.2 PM2 Processes to Remove
```
iqbot-v2-watcher-2    ← DELETE
iqbot-v2-watcher-54   ← DELETE
(any future watcher-N)
```

### 3.3 Redis Channels to Remove
```
trade-requests:*      ← Bot no longer publishes here
trade-results:*       ← Bot no longer subscribes here
balance-updates:*     ← Balance queried on-demand
```

### 3.4 Code to Remove
- `main_bot.py`: watcher spawning after onboard
- `bot/handlers/onboard.py`: `spawn_watcher()` call
- `bot/handlers/trade.py`: Redis publish/subscribe for trade execution
- `bot/admin/system.py`: watcher status display
- `ecosystem.config.js`: watcher app definitions

---

## 4. New Module: `core/trade_executor.py`

### 4.1 Public API

```python
async def execute_trade(
    ssid: str,
    platform_id: int,
    pair: str,              # e.g., "EURUSD-OTC" or "front.EURUSD-OTC"
    direction: str,         # "call" or "put"
    amount: float,
    duration_seconds: int,  # 30, 60, 300, 600
    balance_type: str,      # "REAL" or "PRACTICE"
    timeout_result: int = None,  # default: duration_seconds + 60
) -> dict:
    """
    Connect to IQ Option, place a trade, wait for result, disconnect.

    Returns:
        {"status": "WIN", "pnl": 8.50, "trade_id": "123456", "pair": "EURUSD-OTC", ...}
        {"status": "LOSS", "pnl": -10.0, ...}
        {"status": "TIE", "pnl": 0.0, ...}
        {"status": "TIMEOUT", "error": "Trade result not received within 90s"}
        {"status": "ERROR", "error": "IQ Option message here..."}

    Raises:
        Never. All errors returned as result dict with status="ERROR".
    """
```

### 4.2 Internal Flow

```python
async def execute_trade(ssid, platform_id, pair, direction, amount, duration_seconds, balance_type, timeout_result=None):
    ws = None
    try:
        # 1. Connect
        ws = await websockets.connect(WS_URL, ...)
        
        # 2. Auth
        rid = gen_request_id()
        await ws.send(msg_authenticate(ssid, rid))
        auth_resp = await _wait_for(ws, rid, timeout=10)
        if not auth_resp.get('msg', {}).get('success'):
            return {"status": "ERROR", "error": "Authentication failed"}
        
        # 3. setOptions
        rid = gen_request_id()
        await ws.send(msg_set_options(rid))
        await _wait_for(ws, rid, timeout=5)
        
        # 4. Get balances (to pick balance_id)
        rid = gen_request_id()
        await ws.send(msg_get_balances(rid))
        balances = await _wait_for(ws, rid, timeout=5)
        balance_id = _pick_balance_id(balances, balance_type)
        if not balance_id:
            return {"status": "ERROR", "error": f"No {balance_type} balance found"}
        
        # 5. Get init data (to resolve pair → active_id)
        rid = gen_request_id()
        await ws.send(msg_get_initialization_data(rid))
        init_data = await _wait_for(ws, rid, timeout=10)
        active_id = _resolve_active_id(init_data, pair)
        if not active_id:
            return {"status": "ERROR", "error": f"Unknown pair: {pair}"}
        
        # 6. Subscribe to position-state (to receive result)
        rid = gen_request_id()
        await ws.send(msg_subscribe_position_state(rid))
        
        # 7. Place trade
        rid = gen_request_id()
        expired_at = int(time.time()) + duration_seconds
        option_type_id = 3 if duration_seconds <= 300 else 1
        profit_percent = _get_profit_percent(init_data, active_id)
        
        await ws.send(msg_open_binary_option(
            active_id, direction, expired_at, amount,
            balance_id, profit_percent, option_type_id, rid
        ))
        
        place_result = await _wait_for(ws, rid, timeout=10)
        trade_iq_id = place_result.get('id') if isinstance(place_result, dict) else None
        
        if not trade_iq_id:
            error_msg = place_result.get('message', 'Trade rejected') if isinstance(place_result, dict) else 'No trade ID'
            return {"status": "ERROR", "error": error_msg}
        
        # 8. Wait for position-changed event
        if timeout_result is None:
            timeout_result = duration_seconds + 60
        
        deadline = time.time() + timeout_result
        while time.time() < deadline:
            raw = await asyncio.wait_for(ws.recv(), timeout=min(deadline - time.time(), 5))
            msg = json.loads(raw)
            if msg.get('name') in ('position-changed', 'portfolio.position-changed'):
                body = msg.get('msg', {})
                if body.get('external_id') == trade_iq_id and body.get('status') == 'closed':
                    pnl = body.get('close_profit', 0)
                    close_reason = body.get('close_reason', '')
                    result_status = 'WIN' if close_reason == 'win' else ('TIE' if close_reason == 'equal' else 'LOSS')
                    return {
                        "status": result_status,
                        "pnl": pnl,
                        "trade_id": trade_iq_id,
                        "pair": pair,
                        "direction": direction,
                        "amount": amount,
                    }
        
        return {"status": "TIMEOUT", "error": f"Trade result not received within {timeout_result}s", "trade_id": trade_iq_id}
    
    except asyncio.TimeoutError:
        return {"status": "ERROR", "error": "IQ Option request timed out"}
    except websockets.ConnectionClosed as e:
        return {"status": "ERROR", "error": f"Connection closed: {e}"}
    except Exception as e:
        return {"status": "ERROR", "error": str(e)}
    finally:
        if ws:
            try:
                await ws.close()
            except:
                pass
```

### 4.3 Helper Functions (in same module)

```python
async def _wait_for(ws, request_id: str, timeout: float = 10) -> dict:
    """Read messages until we get a response with matching request_id."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        raw = await asyncio.wait_for(ws.recv(), timeout=min(deadline - time.time(), 2))
        msg = json.loads(raw)
        if msg.get('request_id') == request_id:
            return msg.get('msg', {})
    raise asyncio.TimeoutError(f"No response for request {request_id[:8]}")

def _pick_balance_id(balances_data: dict, balance_type: str) -> int | None:
    """Extract balance_id matching REAL (type=1) or PRACTICE (type=4)."""
    target_type = 1 if balance_type == 'REAL' else 4
    items = balances_data if isinstance(balances_data, list) else balances_data.get('result', {}).get('items', [])
    for item in items:
        if item.get('type') == target_type:
            return item['id']
    return None

def _resolve_active_id(init_data: dict, pair: str) -> int | None:
    """Find active_id for a pair name (e.g., 'EURUSD-OTC' or 'front.EURUSD-OTC')."""
    for atype in ['turbo', 'binary', 'blitz']:
        section = init_data.get(atype, {})
        actives = section.get('actives', {})
        if isinstance(actives, dict):
            for aid_str, active in actives.items():
                name = active.get('name', '')
                if name == pair or name == f'front.{pair}':
                    return int(aid_str)
    return None

def _get_profit_percent(init_data: dict, active_id: int) -> float:
    """Get profit percentage for an active. Default 80%."""
    for atype in ['turbo', 'binary', 'blitz']:
        section = init_data.get(atype, {})
        actives = section.get('actives', {})
        active = actives.get(str(active_id), {})
        opt = active.get('option', {})
        prof = opt.get('profit', {})
        comm = prof.get('commission', 0)
        if comm:
            return 100 - comm
    return 80.0  # fallback
```

---

## 5. Modified Files

### 5.1 `bot/handlers/trade.py` — `cb_confirm_trade()`

**Before (V2):** Publishes to Redis, waits for watcher response
**After (V3):** Calls `execute_trade()` directly

```python
async def cb_confirm_trade(update, ctx):
    # ... (pair, amount, tf, balance_type already extracted — keep this)
    
    # Read bias from DB (keep)
    bias = get_current_bias(pair, tf)
    if not bias:
        # ... NO_BIAS handling (keep)
    if bias['bullish_percent'] >= 55:
        direction = 'call'
    elif bias['bullish_percent'] <= 45:
        direction = 'put'
    else:
        # ... NEUTRAL_BIAS handling (keep)
    
    # Check balance (keep — uses DB cache from last balance fetch)
    summary = get_user_account_summary(user['id'])
    available = summary['practice_balance'] if balance_type == 'PRACTICE' else summary['real_balance']
    if available < amount:
        # ... insufficient balance (keep)
    
    await update.callback_query.edit_message_text("⏳ *Placing trade...*", parse_mode='Markdown')
    
    # ── NEW: Direct trade execution ──
    from core.trade_executor import execute_trade
    account = get_account_credentials(user['id'])
    fresh_ssid = await refresh_ssid_if_stale(account['id'])
    
    result = await execute_trade(
        ssid=fresh_ssid,
        platform_id=account['platform_id'],
        pair=pair,
        direction=direction,
        amount=amount,
        duration_seconds=tf,
        balance_type=balance_type,
    )
    
    if result['status'] == 'ERROR':
        await update.callback_query.edit_message_text(
            f"❌ Trade failed: {result['error']}",
            parse_mode='Markdown',
        )
        return
    
    if result['status'] == 'TIMEOUT':
        # Log to DB anyway (trade was placed, just result unknown)
        log_trade(...)
        await update.callback_query.edit_message_text(
            "⚠️ Trade placed but result unknown. Check /history shortly.",
        )
        return
    
    # WIN / LOSS / TIE
    log_trade(user_id=user['id'], pair=pair, direction=direction,
              amount=amount, iq_option_id=result['trade_id'], ...)
    
    # Display result (same as current)
    ...
```

### 5.2 `bot/handlers/balance.py` — On-demand balance fetch

Instead of relying on watcher-pushed balance events, fetch balance on-demand:

```python
async def cmd_balance(update, ctx):
    # Option A: Show cached balance from DB (fast)
    summary = get_user_account_summary(user['id'])
    # Display...
    
    # Option B: Refresh from IQ Option (accurate, slower)
    # Connect, fetch balances, update DB, display
```

**Recommendation:** Use DB cache by default with a "Refresh" button that connects to IQ Option.

### 5.3 `bot/handlers/onboard.py` — Remove watcher spawn

Remove the `spawn_watcher()` call after successful onboarding. No persistent watcher needed.

### 5.4 `bot/admin/system.py` — Remove watcher status

Remove watcher status from system panel. Keep bias engine, bot, DB, Redis status.

### 5.5 `main_bot.py` — Remove watcher spawning

Remove any watcher spawning logic. Remove watcher-related imports.

### 5.6 `ecosystem.config.js` — Remove watcher definitions

Remove all `iqbot-v2-watcher-*` app definitions.

---

## 6. What Remains Unchanged

| Component | Reason |
|-----------|--------|
| `bias/` — bias engine | Still computes market bias into DB |
| `core/iq_client.py` | IQOptionClient class kept for reference; `execute_trade()` can use it or bypass it |
| `core/iq_protocol.py` | All message builders still needed |
| `core/iq_login.py` | SSID refresh still needed before each trade |
| `core/redis_bus.py` | Bias engine may still use Redis for internal comms |
| `database/` — all models | Accounts, trades, bias, users unchanged |
| `bot/` — most handlers | Only trade.py and onboard.py modified |
| `main_bot.py` | Still the Telegram bot entry point |
| `main_bias.py` | Bias engine entry point unchanged |

---

## 7. Migration Steps

1. Create `core/trade_executor.py` with `execute_trade()` and helpers
2. Modify `bot/handlers/trade.py` — `cb_confirm_trade()` calls `execute_trade()` directly
3. Modify `bot/handlers/onboard.py` — remove watcher spawn
4. Modify `bot/admin/system.py` — remove watcher status
5. Modify `main_bot.py` — remove watcher imports/spawning
6. Delete `watcher/connection.py`, `main_watcher.py`, `utils/pm2_manager.py`
7. Stop and delete all PM2 watcher processes
8. Update `ecosystem.config.js` — remove watcher sections
9. Restart bot + bias engine
10. Test: onboard new account → /trade → verify result

---

## 8. Success Criteria

- [ ] `/trade` places a trade within 3-5 seconds of button click
- [ ] Trade result (WIN/LOSS/TIE) displayed within duration + 10 seconds
- [ ] No watcher processes running (`pm2 list` shows no watchers)
- [ ] Balance displays correctly (cached from DB, refreshable)
- [ ] Trade errors show IQ Option's actual error message, not "no trade ID"
- [ ] SSID refreshed before each trade (handles expiry gracefully)
- [ ] No Redis channels for trade execution
- [ ] No crash loops, no reconnect bugs, no subscription loss
