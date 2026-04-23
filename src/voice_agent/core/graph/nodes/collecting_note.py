from __future__ import annotations

import logging
from typing import Any

from voice_agent.core.graph.nodes.utils import set_node_data, get_state_data, normalize_value
from voice_agent.core.types import CallState, AppointmentDraft

logger = logging.getLogger(__name__)

def _normalize_notes(value: Any) -> list[str]:
    if value is None:
        return []

    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []

    if not isinstance(value, list):
        return []

    notes: list[str] = []
    seen: set[str] = set()

    for item in value:
        text = str(item).strip()
        if not text:
            continue
        if text in seen:
            continue
        notes.append(text)
        seen.add(text)

    return notes

def _merge_notes(
        current_notes: list[str] | None,
        patch_notes: list[str] | None,
) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()

    for item in (current_notes or []):
        text = str(item).strip()
        if text and text not in seen:
            merged.append(text)
            seen.add(text)

    for item in (patch_notes or []):
        text = str(item).strip()
        if text and text not in seen:
            merged.append(text)
            seen.add(text)

    return merged


async def node_collecting_note(
        state: CallState,
        *,
        sessionmaker,
) -> dict[str, Any]:
    draft: AppointmentDraft = dict(state.get("appointment_draft") or {})
    operator_data = get_state_data(state, 'call_operator')
    operator_output = operator_data.get("operator_output", {})
    notes = _normalize_notes(operator_output.get("notes",[]))
    merged_notes = _merge_notes(draft.get("notes"), notes)
    draft["notes"] = merged_notes
    local_state = {
        "appointment_draft": draft,
    }
    logger.warning(f'local_state: {local_state}')
    return local_state
