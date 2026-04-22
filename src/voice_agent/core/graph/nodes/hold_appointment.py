from __future__ import annotations

from datetime import datetime
import logging
from typing import Any

from voice_agent.core.db.uow import SqlAlchemyUnitOfWork
from voice_agent.core.graph.utils import run_non_interruptible
from voice_agent.core.services.appointments import (
    HoldAppointmentResult,
    hold_requested_appointment,
)
from voice_agent.core.types import CallState, AppointmentDraft, AppointmentStatus, AssistantPhase, NextAction

logger = logging.getLogger(__name__)


async def node_hold_appointment(
        state: CallState,
        *,
        sessionmaker,
) -> dict[str, Any]:
    draft: AppointmentDraft = dict(state.get("appointment_draft") or {})

    requested_time_iso = str(draft.get("requested_time_iso") or "").strip()
    if not requested_time_iso:
        logger.warning("hold_appointment: requested_time_iso missing")
        return {}

    try:
        requested_slot_start = datetime.fromisoformat(requested_time_iso)
    except ValueError:
        logger.warning("hold_appointment: invalid requested_time_iso=%s", requested_time_iso)
        return {}

    async def _commit() -> HoldAppointmentResult:
        async with sessionmaker() as session:
            uow = SqlAlchemyUnitOfWork(session)
            return await hold_requested_appointment(
                uow,
                name=str(draft.get("name") or ""),
                phone=str(draft.get("phone") or ""),
                reason_for_visit=str(draft.get("reason_for_visit") or ""),
                notes=list(draft.get("notes") or []),
                requested_slot_start=requested_slot_start,
            )

    try:
        result = await run_non_interruptible(state, _commit)
    except Exception:
        logger.exception("hold_appointment: failed to persist held appointment")
        return {}

    held_view = result.held_view
    scheduled_view = result.scheduled_view or {}

    for field in ("name", "phone", "reason_for_visit"):
        value = held_view.get(field)
        if value not in (None, ""):
            draft[field] = value

    draft["notes"] = list(held_view.get("notes") or draft.get("notes") or [])
    draft["status"] = AppointmentStatus.HELD
    draft["last_offered_slot_start_at"] = held_view.get("start_at")
    draft["offered_time_confirmed"] = False

    local_state = {
        "appointment_draft": draft,
        "held_appointment_view": held_view,
        "scheduled_appointment_view": scheduled_view,
        "current_appointment_id": int(held_view["id"]) if held_view.get("id") else None,
        "next_action": NextAction.CALL_OPERATOR,
    }
    logger.warning("hold_appointment: local_state=%s", local_state)
    return local_state
