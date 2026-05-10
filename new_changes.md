# Database Schema Migration

## Issue Identified

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
