from __future__ import annotations

import logging
from typing import Any

from voice_agent.core.db.uow import SqlAlchemyUnitOfWork
from voice_agent.core.graph.nodes.utils import set_node_data, get_state_data
from voice_agent.core.graph.utils import run_non_interruptible
from voice_agent.core.services.appointments import (
    confirm_appointment,
    cancel_appointment,
)
from voice_agent.core.types import CallState, AppointmentView, AppointmentDraft, AppointmentStatus, DirectiveKind, \
    DirectiveSourceNode, AssistantPhase, AppointmentField, AssistantDirective, ConfirmationTopic, OperationStatus

logger = logging.getLogger(__name__)


def _build_held_appointment_directives(
        state: CallState,
) -> list[AssistantDirective]:
    directives = []

    for node in ('datetime_extractor', 'schedule_patch_to_requested_time_iso'):
        node_data = get_state_data(state, node)
        node_status = node_data.get('node_status')
        if node_status == OperationStatus.FAILURE:
            directives.append(
                {
                    'field': AppointmentField.REQUESTED_TIME_TEXT,
                    'kind': DirectiveKind.REQUEST_CLARIFY_INFO,
                    'priority': 100,
                    'source': DirectiveSourceNode.HELD_APPOINTMENT_INFO,
                }
            )
            return directives

    draft: AppointmentDraft = dict(state.get("appointment_draft") or {})
    if not draft.get("offered_time_confirmed"):
        directives.extend(
            [
                {
                    "kind": DirectiveKind.INFORM_HELD,
                    "priority": 100,
                    "source": DirectiveSourceNode.HELD_APPOINTMENT_INFO,
                },
                {
                    "kind": DirectiveKind.REQUEST_CONFIRMATION,
                    "confirmation_topic": ConfirmationTopic.HOLD_CONFIRMATION,
                    "priority": 90,
                    "source": DirectiveSourceNode.HELD_APPOINTMENT_INFO,
                }
            ]
        )
    return directives


async def node_held_appointment_info(
        state: CallState
) -> dict[str, Any]:

    directives = _build_held_appointment_directives(state)
    local_state = {}
    if directives:
        set_node_data(local_state, 'held_appointment_info', {'directives': directives})
        set_node_data(local_state, 'held_appointment_info', {"exclusive_directives": True})

    logger.warning(f'=======\nlocal state: {local_state}\n=======')
    return local_state
