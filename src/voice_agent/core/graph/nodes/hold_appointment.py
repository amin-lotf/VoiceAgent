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
    DirectiveSourceNode, AssistantPhase, AppointmentField, AssistantDirective, NextAction

logger = logging.getLogger(__name__)


async def node_hold_appointment(
        state: CallState,
        *,
        sessionmaker,
) -> dict[str, Any]:
    draft: AppointmentDraft = dict(state.get("appointment_draft") or {})
    draft["status"] = AppointmentStatus.HELD
    draft['last_offered_slot_start_at'] = draft['requested_time_iso']
    draft['offered_time_confirmed'] = False
    local_state = {
        'appointment_draft': draft,
        'assistant_phase': AssistantPhase.HOLDING_APPOINTMENT,
        'next_action': NextAction.CALL_OPERATOR
    }
    logger.warning(f'=======\nhold_appointment:local_state: {local_state}\n=======')
    return local_state
