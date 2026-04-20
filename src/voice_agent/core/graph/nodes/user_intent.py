from __future__ import annotations

from typing import Any
from voice_agent.const import NOT_SPECIFIED
from voice_agent.core.types import CallState, UserIntent, NextAction, AssistantIntent, AssistantPhase
import logging

logger = logging.getLogger(__name__)



async def node_user_intent(state: CallState) -> dict[str, Any]:
    user_intent = state.get("user_intent")
    local_state = {}
    if user_intent == UserIntent.BOOK_APPOINTMENT:
        local_state['assistant_phase'] = AssistantPhase.COLLECTING_INFO
        local_state['next_action']= NextAction.CALL_OPERATOR
    else:
        local_state['next_action']= NextAction.ASK_USER
    return local_state
