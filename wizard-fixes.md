# Wizard Fixes — IQ Bot v2

**Date:** 2026-05-09
**Author:** Wizard (Hermes Agent)
**Branch:** master
**Issue:** Bot crash loop — 122+ restarts, Telegram 409 Conflict, balances stale, /start /trade broken

---

## Root Cause

The bot is in a permanent crash loop. Every restart cycle:

1. PM2 sends SIGTERM → old process begins cleanup (aiohttp funnel on :8090, Telegram polling)
2. PM2 waits only **1600ms** (default `kill_timeout`), then sends SIGKILL
3. PM2 waits only **3000ms** (`restart_delay`), then starts new process
4. Old process's Telegram polling connection may still be alive on Telegram's servers
5. New process starts polling → Telegram returns `409 Conflict` (two instances)
6. Bot crashes → PM2 restarts → repeat

**Symptoms explained:**
- `/start` silent → handler runs, tries `reply_text()` → 409 → crash → message never sent
- Balance wrong → watcher publishes correct balance, but bot crashes on display reply
- Trade broken → confirmation callback triggers reply → 409 crash

---

## Fix 1: PM2 Ecosystem Config

**File:** `ecosystem.config.js`

```diff
  {
    name: 'iqbot-v2-bot',
    ...
-   restart_delay: 3000,
+   restart_delay: 8000,
+   kill_timeout: 10000,
    ...
  }
```

- `restart_delay: 8000` — PM2 waits 8 seconds between old process death and new process start. This gives Telegram's servers time to drop the old polling connection.
- `kill_timeout: 10000` — PM2 waits 10 seconds after SIGTERM before escalating to SIGKILL. This gives the aiohttp funnel server and PTB polling time to drain gracefully. The existing signal handler in `main_bot.py` handles SIGTERM correctly; it just needs more time to complete.

---

## Fix 2: Signal Handler Already Present

`main_bot.py` lines 196-210 already implement proper SIGTERM handling:
- Sets a `stop_event` on SIGTERM
- Calls `app.updater.stop()` → `app.stop()` → `app.shutdown()` → `runner.cleanup()`

No code changes needed — the handler works. PM2 was just killing it before it finished.

---

## Application

```bash
pm2 delete iqbot-v2-bot
pm2 start ecosystem.config.js --only iqbot-v2-bot
pm2 save
```

---

## Verification

After restart with new delay:
- `pm2 list` → `iqbot-v2-bot` restarts should drop to 0
- `/start` in Telegram → should respond immediately
- `/balance` → should show correct PRACTICE and LIVE balances
- `/trade` → should present pair selection and execute trades
