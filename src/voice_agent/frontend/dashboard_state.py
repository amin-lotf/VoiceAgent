from __future__ import annotations

from voice_agent.common import parse_dt
from voice_agent.const import DEFAULT_TZ

from typing import Sequence


def get_call_status(*, final_status: str | None, ended_at: str | None) -> str:
    if final_status:
        return final_status
    if ended_at:
        return "completed"
    return "active"


def normalize_selected_call_id(
    call_ids: Sequence[str],
    selected_call_id: str | None,
) -> str:
    if not call_ids:
        raise ValueError("call_ids must not be empty")
    if selected_call_id in call_ids:
        return selected_call_id
    return call_ids[0]


def format_in_default_tz(
    value: str | None,
    *,
    fmt: str,
    missing: str = "-",
) -> str:
    if not value:
        return missing

    dt = parse_dt(value)
    if dt is None:
        return value

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=DEFAULT_TZ)

    return dt.astimezone(DEFAULT_TZ).strftime(fmt)
