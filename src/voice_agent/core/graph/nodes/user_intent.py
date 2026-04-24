from __future__ import annotations

from typing import Any
from voice_agent.const import NOT_SPECIFIED
from voice_agent.core.graph.nodes.utils import get_state_data, normalize_value
from voice_agent.core.types import CallState, UserIntent, NextAction, AssistantIntent, AssistantPhase
import logging

logger = logging.getLogger(__name__)

def _resolve_user_intent(
        previous_intent: UserIntent,
        extracted_intent_raw: str | None,
) -> UserIntent:
    if extracted_intent_raw and extracted_intent_raw != NOT_SPECIFIED:
        try:
            return UserIntent(extracted_intent_raw)
        except Exception:
            logger.warning("Invalid extracted_intent=%s", extracted_intent_raw)
            return UserIntent.UNDECIDED
    if previous_intent and previous_intent != NOT_SPECIFIED:
        return previous_intent
    return UserIntent.UNDECIDED

async def node_user_intent(state: CallState) -> dict[str, Any]:
    logger.warning("********************\nuser_intent: inputted state=%s\n******************", state)
    local_state = {}
    operator_data= get_state_data(state,'call_operator')
    operator_output = operator_data.get("operator_output",{})
    user_intent_raw = normalize_value(operator_output.get("user_intent"))
    previous_intent = state.get("user_intent") or UserIntent.UNDECIDED
    user_intent = _resolve_user_intent(previous_intent, user_intent_raw)

    local_state["user_intent"] = user_intent

    if user_intent == UserIntent.BOOK_APPOINTMENT:
        local_state['assistant_phase'] = AssistantPhase.COLLECTING_INFO
        local_state['next_action']= NextAction.CALL_OPERATOR
        local_state["internal_call"]= True
    else:
        local_state['next_action']= NextAction.ASK_USER
    logger.warning("********************\nuser_intent: local_state=%s\n******************", local_state)
    return local_state
