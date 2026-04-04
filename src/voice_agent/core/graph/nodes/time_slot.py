from __future__ import annotations

from typing import Any, TypedDict
from enum import StrEnum

from voice_agent.const import NOT_SPECIFIED
from voice_agent.core.types import CallState, AppointmentDraft, AppointmentField, AssistantDirective, DirectiveKind, \
    ExtractorNode


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


def _build_time_slot_directives(
    draft: AppointmentDraft,
) -> list[AssistantDirective]:
    directives: list[AssistantDirective] = []

    if _is_missing(draft.get("requested_time_text")):
        directives.append(
            {
                "field": AppointmentField.REQUESTED_TIME_TEXT,
                "kind": DirectiveKind.REQUEST_MISSING_INFO,
                "priority": 70,
                "source": ExtractorNode.TIME_SLOT,
            }
        )
    return directives


async def node_time_slot(state: CallState) -> dict[str, Any]:
    appointment_draft = state.get("appointment_draft") or {}

    directives = _build_time_slot_directives(appointment_draft)

    return {
        "node_data": {
            "basic_info": {
                "directives": directives,
            }
        }
    }