# Wizard Fixes — IQ Bot v2

**Date:** 2026-05-10
**Author:** Wizard (Hermes Agent)
**Branch:** master

---

## Fix Round 1 — Bot Crash Loop (RESOLVED)

**Issue:** Bot crash loop — 122+ restarts, Telegram 409 Conflict

**Root Cause:** PM2 `restart_delay: 3000` too fast — old process Telegram polling still alive when new process starts → 409 Conflict → crash → repeat.

**Fix:**
- `ecosystem.config.js`: `restart_delay: 8000`, `kill_timeout: 10000`
- `pip3 install` all missing deps from `requirements.txt` (python-telegram-bot, python-dotenv, cryptography, telethon)

**Result:** Bot stable — 0 restarts, all commands responsive.

---

## Fix Round 2 — Trades Not Working (CURRENT)

**Symptoms from Telegram (2026-05-10 06:13-06:27):**
- Trade fails with: `sent 1011 (internal error) keepalive ping timeout; no close frame received`
- "Trade result delayed. Check /history shortly."
- Multiple PENDING trades that never resolve
- Live balance shows $0.00 (account not connected)

**Watcher logs confirm:**
```
02:14:50 — WS closed, reconnecting...    ← last reconnection attempt
07:13:35 — Trade execution error: 1011    ← 5 HOURS later, trade on DEAD connection
```

**Three root causes:**

---

### Root Cause #1: Reconnect loop exits prematurely

**File:** `core/iq_client.py`, line 80

```python
# connect() method — BROKEN:
self.ws = await websockets.connect(...)
self.connected = True          # ← SET TOO EARLY (line 80)
# ... authenticate, setOptions, getProfile, getBalances, getInitializationData
# If ANY of those throw, self.connected stays True
```

`_reconnect()` loop checks `while not self.connected` → sees True → exits immediately without retrying.

**Result:** Watcher thinks it's connected but WS is dead. Sits silently for 5 hours.

**Fix:** Move `self.connected = True` to the END of `connect()`, after ALL initialization succeeds. Add `finally` block that sets `self.connected = False` on failure.

---

### Root Cause #2: Position/Balance subscriptions lost on reconnect

**File:** `watcher/connection.py`, lines 56-62

Position-state and balance subscriptions are only sent during initial `start()`. When the client reconnects, `_on_reconnect_cb` only re-subscribes candles — not positions or balances.

**Result:** After any reconnect, position-changed and balance-changed events never arrive → "Trade result delayed" forever.

**Fix:** Move subscription logic into a method, register it as `on_reconnect` callback so it replays after every reconnect.

---

### Root Cause #3: No pre-trade connection check

**File:** `watcher/connection.py`, line 151

`_execute_trade()` calls `self.client.place_binary_option()` without verifying `self.client.connected` is True or that `self.client.ws` is alive.

**Fix:** Add `if not self.client.connected or not self.client.ws:` check before trade, publish error to Redis immediately instead of letting 1011 crash through.

---

## Fixes Applied

### Fix to `core/iq_client.py` — `connect()` method

```python
async def connect(self):
    self._connecting = True
    logger.info("Connecting to IQ Option WS...")
    headers = { ... }

    try:
        self.ws = await websockets.connect(WS_URL, ...)

        if self._receive_task and not self._receive_task.done():
            self._receive_task.cancel()
        self._receive_task = asyncio.create_task(self._receive_loop())

        # Auth + init steps...
        await self._request(...)  # authenticate
        self.authenticated = True
        await self._request(...)  # setOptions
        self.profile = await self._request(...)  # getProfile
        await self._refresh_balances()
        await self._refresh_initialization_data()

        # ONLY NOW mark connected
        self.connected = True
        logger.info(f"Client ready. {len(self.balances)} balances, {len(self.actives)} actives")
    except Exception:
        self.connected = False
        self.authenticated = False
        raise
    finally:
        self._connecting = False
```

### Fix to `watcher/connection.py` — Re-subscribe on reconnect

```python
async def _subscribe_streams(self):
    """Re-subscribe position + balance streams (called on init + reconnect)."""
    req_id = gen_request_id()
    await self.client.ws.send(msg_subscribe_position_state(req_id))
    logger.info(f"Sent position-state subscription (req_id={req_id})")
    for bal_id in self.client.balances:
        req_id = gen_request_id()
        await self.client.ws.send(msg_subscribe_balance(bal_id, req_id))
        logger.info(f"Sent balance subscription bal_id={bal_id}")

# In start(), register as reconnect callback:
self.client.on_reconnect(self._subscribe_streams)
```

### Fix to `watcher/connection.py` — Pre-trade connection check

```python
async def _execute_trade(self, req: dict):
    if not self.client or not self.client.connected or not self.client.ws:
        await publish(f'trade-results:{self.user_id}', {
            'request_token': req.get('request_token'),
            'status': 'ERROR',
            'error': 'IQ Option connection is not active. Please wait for reconnection.',
        })
        return
    # ... rest of trade execution
```

---

## Verification

After applying fixes:
1. `pm2 restart all` — watcher should reconnect fully
2. Watcher logs should show re-subscription after reconnect
3. `/trade` in Telegram → should execute immediately (not "delayed")
4. Trade results should resolve within 30-60s (not stuck PENDING)
