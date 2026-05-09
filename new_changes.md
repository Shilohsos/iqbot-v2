# Database Schema Migration

## Required Migration

The `market_bias` table needs one new column that was added to the schema in `database/db.py` but only affects new databases. Existing databases need an ALTER TABLE.

### Migration SQL

```sql
ALTER TABLE market_bias ADD COLUMN is_suspended INTEGER NOT NULL DEFAULT 0;
```

### When to Apply

Run this `ALTER TABLE` before restarting the PM2 processes. Without it, the bias engine will crash on the first candle close because `INSERT OR REPLACE INTO market_bias` tries to write 12 values into an 11-column table.

### Verification

```sql
-- Check if the column already exists
PRAGMA table_info(market_bias);
```

The output should include `is_suspended` in the list of columns.

