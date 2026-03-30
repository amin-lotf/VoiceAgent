from __future__ import annotations

import logging

from langgraph.config import get_stream_writer

from voice_agent.core.db.uow import SqlAlchemyUnitOfWork
from voice_agent.core.graph.nodes.utils import stream_text_response, view_id
from voice_agent.core.graph.utils import run_non_interruptible
from voice_agent.core.services.appointments import delete_held_appointment
from voice_agent.core.types import CallState, CallPhase, AppointmentStatus

logger = logging.getLogger(__name__)


async def _delete_held_view(
    state: CallState,
    *,
    sessionmaker,
    appointment_id: int,
) -> bool:
    async def _commit() -> bool:
        async with sessionmaker() as session:
            uow = SqlAlchemyUnitOfWork(session)
            return await delete_held_appointment(
                uow,
                appointment_id=appointment_id,
            )

    return await run_non_interruptible(state, _commit)


async def node_on_call_ended(state: CallState,
                       *,
                       sessionmaker
                       ) -> dict:
    """Cleanup node after hangups."""

    cur_view = state.get("current_appointment_view") or {}
    view_status= cur_view.get("appointment_status")
    if view_status not in (AppointmentStatus.HELD, AppointmentStatus.PENDING):
        return {}

    held_id = view_id(cur_view)
    local_state = {}
    try:
        if held_id is not None:
            view_deleted = await _delete_held_view(
                state,
                sessionmaker=sessionmaker,
                appointment_id=held_id,
            )
            if view_deleted:
                local_state["current_appointment_view"] =  {}

    except Exception:
        logger.exception("Failed to delete held appointment")
    return local_state


def node_handle_hangup(state: CallState) -> dict:
    # text = "Thanks for calling. If you need anything else, reach out anytime."
    # local_state = stream_text_response(text)
    local_state = {
        "end_call": True,
        "phase": CallPhase.DONE
    }
    return local_state
