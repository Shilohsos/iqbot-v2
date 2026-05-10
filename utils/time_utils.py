from datetime import datetime, timezone, timedelta

WAT = timezone(timedelta(hours=1))  # West Africa Time


def now_wat() -> datetime:
    return datetime.now(WAT)


def today_str() -> str:
    return now_wat().strftime('%Y-%m-%d')


def yesterday_str() -> str:
    return (now_wat() - timedelta(days=1)).strftime('%Y-%m-%d')


def weekday_str() -> str:
    return now_wat().strftime('%A, %d %b %Y')


def ago_since(dt_str: str) -> str:
    """Human-readable time since a datetime string."""
    if not dt_str:
        return 'never'
    try:
        dt = datetime.fromisoformat(dt_str)
        # SQLite CURRENT_TIMESTAMP is UTC but timezone-naive; attach UTC before converting
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = now_wat() - dt.astimezone(WAT)
        hours = delta.total_seconds() / 3600
        if hours < 1:
            return f"{int(delta.total_seconds() / 60)}m ago"
        elif hours < 24:
            return f"{int(hours)}h ago"
        else:
            return f"{int(hours / 24)}d ago"
    except Exception:
        return 'unknown'
