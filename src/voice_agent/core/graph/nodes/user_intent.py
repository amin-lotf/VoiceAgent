from __future__ import annotations

from typing import Any, TypedDict
from enum import StrEnum

from voice_agent.const import NOT_SPECIFIED
from voice_agent.core.types import CallState, AppointmentDraft, AppointmentField, AssistantDirective, DirectiveKind, \
    DirectiveSourceNode, UserIntent, NextAction


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
    if  directives:
        local_state = {'next_action': NextAction.ASK_USER}
    local_state["node_data"] = {
        "user_intent": {
            "directives": directives,
        }
    }
    return local_state
