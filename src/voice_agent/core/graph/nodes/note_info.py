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


def _build_note_info_directives(
    draft: AppointmentDraft,
) -> list[AssistantDirective]:
    directives = [
        {
            "field": AppointmentField.NOTES,
            "kind": DirectiveKind.REQUEST_MISSING_INFO,
            "priority": 90,
            "source": DirectiveSourceNode.BOOK_APPOINTMENT,
        }
    ]
    return directives

async def node_note_info(
        state: CallState,
) -> dict[str, Any]:
    draft: AppointmentDraft = dict(state.get("appointment_draft") or {})

    directives = _build_note_info_directives(draft)
    local_state = {}
    set_node_data(local_state,'note_info',{'directives': directives})

    logger.warning(f'local_state: {local_state}')
    return local_state
