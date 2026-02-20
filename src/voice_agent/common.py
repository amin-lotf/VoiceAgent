from datetime import datetime, timezone


def utcnow() -> datetime:
    # Ensures tz-aware "now"
    return datetime.now(timezone.utc)