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
    DirectiveSourceNode, AssistantPhase, AppointmentField, AssistantDirective

logger = logging.getLogger(__name__)


def _build_book_appointment_directives(
    draft: AppointmentDraft,
) -> list[AssistantDirective]:
    directives = [
        {
            "kind": DirectiveKind.INFORM_SCHEDULED,
            "priority": 100,
            "source": DirectiveSourceNode.BOOK_APPOINTMENT,
        },
        {
            "field": AppointmentField.NOTES,
            "kind": DirectiveKind.REQUEST_MISSING_INFO,
            "priority": 90,
            "source": DirectiveSourceNode.BOOK_APPOINTMENT,
        }
    ]
    return directives

async def node_book_appointment(
        state: CallState,
        *,
        sessionmaker,
) -> dict[str, Any]:
    draft: AppointmentDraft = dict(state.get("appointment_draft") or {})
    draft["status"] = AppointmentStatus.SCHEDULED

    directives = _build_book_appointment_directives(draft)

    local_state = { 'appointment_draft': draft, 'assistant_phase': AssistantPhase.POST_APPOINTMENT}
    set_node_data(local_state,'book_appointment',{'directives': directives})
    set_node_data(local_state,'book_appointment',{"exclusive_directives": True})

    logger.warning(f'local_state: {local_state}')
    return local_state
