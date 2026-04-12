from __future__ import annotations

from typing import Any, TypedDict
from enum import StrEnum

from voice_agent.const import NOT_SPECIFIED
from voice_agent.core.graph.nodes.utils import get_state_data, set_node_data
from voice_agent.core.types import CallState, AppointmentDraft, AppointmentField, AssistantDirective, DirectiveKind, \
    DirectiveSourceNode, UserIntent, NextAction
import logging

logger = logging.getLogger(__name__)

def _is_missing(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and value.strip().lower() in {
        "",
        "not_specified",
        str(NOT_SPECIFIED).lower(),
    }:
        return True
    return False


def _build_user_intent_directives(
        user_intent: UserIntent | None,
) -> list[AssistantDirective]:
    directives: list[AssistantDirective] = []

    if _is_missing(user_intent):
        directives.append(
            {
                "kind": DirectiveKind.REQUEST_USER_INTENT,
                "priority": 110,
                "source": DirectiveSourceNode.USER_INTENT,
            }
        )
    return directives


async def node_user_intent(state: CallState) -> dict[str, Any]:
    user_intent = state.get("user_intent")

    directives = _build_user_intent_directives(user_intent)
    local_state = {}
    if directives:
        local_state = {'next_action': NextAction.ASK_USER}
    else:
        patch_resolver = get_state_data(state, 'patch_resolver')
        user_intent_updated = patch_resolver.get('user_intent_updated') or False
        if user_intent_updated:
            local_state = {'next_action': NextAction.CALL_OPERATOR}

    set_node_data(
        local_state,
        "user_intent",
        {
                "directives": directives,
        }
    )

    logger.warning("======\n user_intent: local state: %s \n ======", local_state)
    return local_state
