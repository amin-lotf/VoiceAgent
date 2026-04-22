from __future__ import annotations

from typing import Any

from voice_agent.const import NOT_SPECIFIED
from voice_agent.core.db.mappers import to_view
from voice_agent.core.db.uow import SqlAlchemyUnitOfWork
from voice_agent.core.graph.nodes.utils import get_state_data, view_id
from voice_agent.core.graph.utils import run_non_interruptible
from voice_agent.core.types import CallState, NextAction, AppointmentDraft, AppointmentPatch, AppointmentStatus, \
    AppointmentView, OperationStatus, AssistantPhase
import logging

logger = logging.getLogger(__name__)


async def node_verify_info(
        state: CallState,
) -> dict[str, Any]:
    next_action = state.get('next_action')
    # if next_action!=NextAction.CHECK_INFO:
    local_state ={
        'assistant_phase': AssistantPhase.CONFIRMING_SLOT
    }
    if next_action!=NextAction.MARK_VERIFIED:
        local_state['next_action'] = NextAction.EXTRACT_DATETIME
    logger.warning(f'verify_info:next_action: {next_action}')
    return local_state




