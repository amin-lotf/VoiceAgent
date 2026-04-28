from __future__ import annotations

from datetime import datetime
import logging
from typing import Any

from voice_agent.core.db.uow import SqlAlchemyUnitOfWork
from voice_agent.core.graph.utils import run_non_interruptible, record_node_error, mark_node_succeeded, \
    prep_internal_operator_call
from voice_agent.core.services.appointments import (
    HoldAppointmentResult,
    hold_requested_appointment,
)
from voice_agent.core.types import CallState, AppointmentDraft, AppointmentStatus, AssistantPhase, NextAction, ErrorType

logger = logging.getLogger(__name__)


async def node_hold_appointment(
        state: CallState,
        *,
        sessionmaker,
) -> dict[str, Any]:
    local_state = {}
    draft: AppointmentDraft = dict(state.get("appointment_draft") or {})
    try:
        requested_time_iso = str(draft.get("requested_time_iso") or "").strip()
        requested_slot_start = datetime.fromisoformat(requested_time_iso)
    except ValueError as exc:
        logger.warning("hold_appointment: invalid requested_time_iso=%s", requested_time_iso)
        # Better to retry datetime extractor agent to see if error is fixed
        local_state.update(
            record_node_error(
                state,
                node_name="datetime_extractor",
                error_type=ErrorType.LLM_CALL,
                error_message=str(exc)
            )
        )
        local_state['next_action'] = NextAction.REPORT_ERROR
        return local_state

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
    except Exception as exc:
        logger.exception("hold_appointment: failed to persist held appointment")
        local_state.update(
            record_node_error(
                state,
                node_name="hold_appointment",
                error_type=ErrorType.DB_ERROR,
                error_message=str(exc)
            )
        )
        local_state['next_action'] = NextAction.REPORT_ERROR
        return local_state

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
    local_state.update(prep_internal_operator_call(state, clear_messages=True))
    local_state.update(
        {
            "appointment_draft": draft,
            "held_appointment_view": held_view,
            "scheduled_appointment_view": scheduled_view,
            "current_appointment_id": int(held_view["id"]) if held_view.get("id") else None,
        }
    )
    mark_node_succeeded(state, local_state, "hold_appointment")
    logger.warning("hold_appointment: local_state=%s", local_state)
    return local_state
