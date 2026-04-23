from __future__ import annotations

import logging
from typing import Any

from voice_agent.core.db.uow import SqlAlchemyUnitOfWork
from voice_agent.core.graph.nodes.utils import set_node_data, get_state_data, normalize_value, view_id
from voice_agent.core.graph.utils import run_non_interruptible
from voice_agent.core.services.appointments import update_appointment_notes
from voice_agent.core.types import CallState, AppointmentDraft, AppointmentView

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
    scheduled_view = state.get("scheduled_appointment_view") or {}
    operator_data = get_state_data(state, 'call_operator')
    operator_output = operator_data.get("operator_output", {})
    notes = _normalize_notes(operator_output.get("notes",[]))
    merged_notes = _merge_notes(draft.get("notes"), notes)
    scheduled_id = view_id(scheduled_view)
    if scheduled_id is None:
        logger.warning("book_appointment: scheduled_appointment_view missing")
        return {}
    async def _commit() -> AppointmentView:
        async with sessionmaker() as session:
            uow = SqlAlchemyUnitOfWork(session)
            return await update_appointment_notes(
                uow,
                appointment_id=scheduled_id,
                notes=merged_notes,
            )

    try:
        persisted_scheduled_view = await run_non_interruptible(state, _commit)
    except Exception:
        logger.exception("hold_appointment: failed to persist held appointment")
        return {}
    draft["notes"] = list(persisted_scheduled_view.get("notes") or draft.get("notes") or [])
    local_state = {
        "appointment_draft": draft,
        "scheduled_appointment_view": persisted_scheduled_view,
    }
    logger.warning(f'local_state: {local_state}')
    return local_state
