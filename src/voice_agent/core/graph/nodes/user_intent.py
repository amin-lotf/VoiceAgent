from __future__ import annotations

from typing import Any
from voice_agent.const import NOT_SPECIFIED
from voice_agent.core.graph.nodes.utils import get_state_data, normalize_value
from voice_agent.core.graph.utils import prep_internal_operator_call
from voice_agent.core.types import CallState, UserIntent, NextAction, AssistantIntent, AssistantPhase
import logging

logger = logging.getLogger(__name__)


async def node_user_intent(state: CallState) -> dict[str, Any]:
    local_state = {}
    user_intent = state.get("user_intent") or UserIntent.UNDECIDED

    if user_intent == UserIntent.BOOK_APPOINTMENT:
        local_state.update(prep_internal_operator_call(state, clear_messages=False))
        local_state['assistant_phase'] = AssistantPhase.COLLECTING_INFO
    else:
        local_state['next_action']= NextAction.ASK_USER
    logger.info(
        f"Next action: {local_state['next_action']}",
        extra={
            'call_id': state.get('call_id'),
            'phase': state.get('assistant_phase'),
            'node': 'user_intent',

        })
    return local_state
