from __future__ import annotations

import logging

from voice_agent.core.db.uow import SqlAlchemyUnitOfWork
from voice_agent.core.graph.nodes.utils import view_id
from voice_agent.core.graph.utils import run_non_interruptible, record_node_error
from voice_agent.core.services.appointments import delete_held_appointment
from voice_agent.core.types import CallState, CallPhase, AppointmentStatus, ErrorType, NextAction

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

    held_view = state.get("held_appointment_view") or {}
    view_status = held_view.get("status")
    if view_status not in (AppointmentStatus.HELD, AppointmentStatus.PENDING):
        return {}

    held_id = view_id(held_view)
    local_state = {}
    try:
        if held_id is not None:
            view_deleted = await _delete_held_view(
                state,
                sessionmaker=sessionmaker,
                appointment_id=held_id,
            )
            if view_deleted:
                local_state["held_appointment_view"] = {}
                if state.get("current_appointment_id") == held_id:
                    local_state["current_appointment_id"] = None
        logger.info(
            f"Data cleanup completed",
            extra={
                'call_id': state.get('call_id'),
                'phase': state.get('assistant_phase'),
                'node': 'on_call_ended',
            }
        )
        return local_state

    except Exception as exc:
        local_state.update(
            record_node_error(
                state,
                node_name="datetime_extractor",
                error_type=ErrorType.DB_ERROR,
                error_message=str(exc)
            )
        )
        local_state['next_action'] = NextAction.REPORT_ERROR
        logger.exception(
            f"Failed to delete held appointment",
            extra={
                'call_id': state.get('call_id'),
                'phase': state.get('assistant_phase'),
                'node': 'on_call_ended',

            }
        )
        return local_state


def node_handle_hangup(state: CallState) -> dict:
    # text = "Thanks for calling. If you need anything else, reach out anytime."
    # local_state = stream_text_response(text)
    local_state = {
        "end_call": True,
        "phase": CallPhase.DONE
    }
    logger.info(
        f"Hangup detected.",
        extra={
            'call_id': state.get('call_id'),
            'phase': state.get('assistant_phase'),
            'node': 'handle_hangup',
        }
    )
    return local_state
