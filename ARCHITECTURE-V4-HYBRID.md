# Architecture V4: Hybrid — TypeScript Trade Executor + Python Bot

**Date:** 2026-05-10  
**Author:** Wizard  
**Status:** Proposed

---

## The Problem

Every IQ Option protocol issue is a reverse-engineering effort. `socket-option-closed` doesn't arrive, `subscribeMessage` vs `sendMessage` wrong format, event names mismatch between SDK and reality. Each fix takes hours and another one always follows. We're maintaining a parallel SDK that already exists.

## The Solution

Spin the **trade executor** out into a Node.js microservice that uses the **official Quadcode client-sdk-js** directly. The Python bot handles everything else (Telegram, bias engine, DB, admin).

```
┌─────────────────────────────────────────────────┐
│                   Python Bot                     │
│  Telegram handlers / Bias engine / DB / Admin   │
└──────────┬──────────────────────────────────────┘
           │ HTTP/Redis (send trade request)
           ▼
┌─────────────────────────────────────────────────┐
│          Node.js Trade Executor (iq-pass)        │
│     Uses official Quadcode SDK → IQ Option       │
│     Result events delivered natively             │
└─────────────────────────────────────────────────┘
```

## How It Works

1. **User clicks "Trade"** in Telegram → Python bot validates (bias, balance, tier) → sends trade request to Node.js service via HTTP POST
2. **Node.js service** (50 lines, Express) → receives request → uses SDK to connect → authenticate → place trade → **awaits result using SDK's native event system** → returns result
3. **Python bot** receives result → logs to DB → delivers to user via Telegram

## What Changes

### New: `iq-trader/` directory

A minimal Node.js project:
- `package.json` — express, the SDK from `iq-pass/`
- `server.js` — POST `/trade` endpoint, POST `/balance` endpoint
- Uses SDK's `ClientSdk.connect()` → `openBinaryOption()` → wait for result

### Minimal changes to Python bot

- `core/trade_executor.py` — replace `execute_trade()` with an HTTP POST to `http://localhost:3001/trade`
- `core/fetch_balances.py` — or keep as HTTP call too
- `ecosystem.config.js` — add `iq-trader` as a PM2 process

Everything else stays exactly as-is: Telegram handlers, bias engine, DB, admin panel.

## Benefits

| Issue | Current (all Python) | Hybrid |
|---|---|---|
| Protocol guesswork | Every fix is trial-and-error | SDK knows the exact format |
| `position-changed` not arriving | Months of debugging | Works out of the box |
| New IQ update breaks bot | Manual investigation | SDK authors update first |
| `setOptions` format | Unknown if correct | SDK confirms |
| One-shot WS connection | Custom implementation | SDK handles natively |

## Effort

- **Node.js service:** ~50-80 lines of code (Express wrapper around SDK)
- **Python changes:** ~30 lines (replace WS calls with HTTP)
- **PM2 config:** 1 line (add iq-trader process)
- **Total:** ~1 hour dev time

## Files to Create

### `iq-trader/server.js`

```javascript
const express = require('express');
const { ClientSdk } = require('./client-sdk-js');

const app = express();
app.use(express.json());

app.post('/trade', async (req, res) => {
    const { ssid, platformId, pair, direction, amount, durationSeconds, balanceType } = req.body;
    
    const sdk = new ClientSdk({
        ssid,
        platformId,
    });
    
    // SDK handles connect → auth → subscribe → trade → wait for result
    const result = await sdk.executeTrade({
        pair,
        direction,
        amount,
        duration: durationSeconds,
        balanceType,
    });
    
    await sdk.disconnect();
    res.json(result);
});
```

### `iq-trader/package.json`

```json
{
    "name": "iq-trader",
    "version": "1.0.0",
    "dependencies": {
        "express": "^4.18.0",
        "client-sdk-js": "file:../iq-pass"
    }
}
```

## Risk

Very low. The Python trade executor stays as-is until the Node.js one is verified working. No existing code deleted. Rollback = remove PM2 process + restore `trade_executor.py`.

---

**Decision needed:** Proceed with V4?
