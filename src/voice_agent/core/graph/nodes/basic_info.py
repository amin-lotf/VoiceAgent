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


def _build_basic_info_directives(
    draft: AppointmentDraft,
) -> list[AssistantDirective]:
    directives: list[AssistantDirective] = []

    if _is_missing(draft.get("phone")):
        directives.append(
            {
                "field": AppointmentField.PHONE,
                "kind": DirectiveKind.REQUEST_MISSING_INFO,
                "priority": 100,
                "source": ExtractorNode.BASIC_INFO,
            }
        )


    if _is_missing(draft.get("name")):
        directives.append(
            {
                "field": AppointmentField.NAME,
                "kind": DirectiveKind.REQUEST_MISSING_INFO,
                "priority": 90,
                "source": ExtractorNode.BASIC_INFO,
            }
        )


    if _is_missing(draft.get("reason_for_visit")):
        directives.append(
            {
                "field": AppointmentField.REASON_FOR_VISIT,
                "kind": DirectiveKind.REQUEST_MISSING_INFO,
                "priority": 80,
                "source": ExtractorNode.BASIC_INFO,
            }
        )

    return directives


async def node_basic_info(state: CallState) -> dict[str, Any]:
    appointment_draft = state.get("appointment_draft") or {}

    directives = _build_basic_info_directives(appointment_draft)

    return {
        "node_data": {
            "basic_info": {
                "directives": directives,
            }
        }
    }