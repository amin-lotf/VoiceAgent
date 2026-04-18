from __future__ import annotations

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
