from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from voice_agent.const import DEFAULT_TZ


def utcnow() -> datetime:
    # Ensures tz-aware "now"
    return datetime.now(timezone.utc)





def parse_dt(value: object) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def to_default_tz_iso(value: object) -> str | None:
    dt = parse_dt(value)
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=DEFAULT_TZ)
    return dt.astimezone(DEFAULT_TZ).isoformat()