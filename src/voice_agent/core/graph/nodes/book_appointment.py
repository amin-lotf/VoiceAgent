from __future__ import annotations

import logging
from typing import Any

from voice_agent.core.db.uow import SqlAlchemyUnitOfWork
from voice_agent.core.graph.nodes.utils import set_node_data, view_id
from voice_agent.core.graph.utils import run_non_interruptible, record_node_error
from voice_agent.core.services.appointments import (
    ScheduleAppointmentResult,
    schedule_held_appointment,
)
from voice_agent.core.types import (CallState, AppointmentDraft, AppointmentStatus
, AssistantPhase, AppointmentField, NextAction, ErrorType)

logger = logging.getLogger(__name__)


async def node_book_appointment(
        state: CallState,
        *,
        sessionmaker,
) -> dict[str, Any]:
    local_state = {}
    draft: AppointmentDraft = dict(state.get("appointment_draft") or {})
    held_view = state.get("held_appointment_view") or {}
    scheduled_view = state.get("scheduled_appointment_view") or {}

    held_id = view_id(held_view)
    scheduled_id = view_id(scheduled_view)
    if held_id is None:
        logger.warning("book_appointment: held_appointment_view missing")
        return {}

    async def _commit() -> ScheduleAppointmentResult:
        async with sessionmaker() as session:
            uow = SqlAlchemyUnitOfWork(session)
            return await schedule_held_appointment(
                uow,
                held_appointment_id=held_id,
                scheduled_appointment_id=scheduled_id,
            )

    try:
        result = await run_non_interruptible(state, _commit)
    except Exception as exc:
        logger.exception("book_appointment: failed to schedule held appointment")
        local_state.update(
            record_node_error(
                state,
                node_name="book_appointment",
                error_type=ErrorType.DB_ERROR,
                error_message=str(exc)
            )
        )
        local_state['next_action'] = NextAction.REPORT_ERROR
        return local_state

    persisted_scheduled_view = result.scheduled_view
    for field in ("name", "phone", "reason_for_visit"):
        value = persisted_scheduled_view.get(field)
        if value not in (None, ""):
            draft[field] = value

    draft["notes"] = list(persisted_scheduled_view.get("notes") or draft.get("notes") or [])
    draft["status"] = AppointmentStatus.SCHEDULED
    draft["last_offered_slot_start_at"] = persisted_scheduled_view.get("start_at")
    draft["offered_time_confirmed"] = True

    local_state.update(
            {
            "appointment_draft": draft,
            "scheduled_appointment_view": persisted_scheduled_view,
            "held_appointment_view": {},
            "current_appointment_id": int(persisted_scheduled_view["id"]) if persisted_scheduled_view.get("id") else None,
            "assistant_phase": AssistantPhase.COLLECTING_NOTES,
            "next_action": NextAction.CALL_OPERATOR,
            "internal_call": True
        }
    )

    logger.warning("book_appointment: local_state=%s", local_state)
    return local_state
