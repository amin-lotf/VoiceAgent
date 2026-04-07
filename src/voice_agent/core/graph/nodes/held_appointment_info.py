from __future__ import annotations

import logging
from typing import Any

from voice_agent.core.db.uow import SqlAlchemyUnitOfWork
from voice_agent.core.graph.nodes.utils import set_node_data
from voice_agent.core.graph.utils import run_non_interruptible
from voice_agent.core.services.appointments import (
    confirm_appointment,
    cancel_appointment,
)
from voice_agent.core.types import CallState, AppointmentView, AppointmentDraft, AppointmentStatus, DirectiveKind, \
    ExtractorNode, AssistantPhase, AppointmentField, AssistantDirective

logger = logging.getLogger(__name__)


def _build_held_appointment_directives(
        draft: AppointmentDraft,
) -> list[AssistantDirective]:
    directives = []
    if not draft.get("offered_time_confirmed"):
        directives.extend(
            [
                {
                    "kind": DirectiveKind.INFORM_HELD,
                    "priority": 100,
                    "source": ExtractorNode.HOLD_APPOINTMENT,
                },
                {
                    "kind": DirectiveKind.REQUEST_HOLD_CONFIRMATION,
                    "priority": 90,
                    "source": ExtractorNode.HOLD_APPOINTMENT,
                }
            ]
        )
    return directives


async def node_held_appointment_info(
        state: CallState,
        *,
        sessionmaker,
) -> dict[str, Any]:
    draft: AppointmentDraft = dict(state.get("appointment_draft") or {})

    directives = _build_held_appointment_directives(draft)
    local_state = {}
    if directives:
        set_node_data(local_state, 'hold_appointment', {'directives': directives})
        set_node_data(local_state, 'hold_appointment', {"exclusive_directives": True})

    logger.warning(f'held_appointment_info: {local_state}')
    return local_state
