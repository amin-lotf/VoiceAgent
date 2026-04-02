from __future__ import annotations

from voice_agent.const import NOT_SPECIFIED
from voice_agent.core.types import (
    CallState,
    AssistantDirective,
    AppointmentField,
    DirectiveKind,
)
from voice_agent.core.prompts.operator_blocks import (
    PATCH_FIELD_RULES,
    REQUESTING_FIELD_RULES,
    EXISTING_FIELD_RULES,
    INFORMATIVE_DIRECTIVE_RULES,
)
import logging

logger = logging.getLogger(__name__)


def _has_value(v):
    return v not in (None, "", NOT_SPECIFIED)


def _build_field_rules(
    state: CallState,
    directives: list[AssistantDirective],
) -> list[str]:
    draft = state.get("appointment_draft") or {}
    rules: list[str] = []

    active_fields = {
        d.get("field")
        for d in directives
        if d.get("field") and d.get("kind") == DirectiveKind.REQUEST_MISSING_INFO
    }

    for field in PATCH_FIELD_RULES.keys():
        if field in active_fields:
            rules.extend(REQUESTING_FIELD_RULES[field])
            continue

        if _has_value(draft.get(field.value)):
            rules.extend(EXISTING_FIELD_RULES[field])

    return rules


def _build_informative_rules(
    state: CallState,
    directives: list[AssistantDirective],
) -> list[str]:
    rules: list[str] = []

    seen_kinds: set[DirectiveKind] = set()

    for directive in directives:
        kind = directive.get("kind")
        if not kind or kind in seen_kinds:
            continue

        seen_kinds.add(kind)
        rules.extend(INFORMATIVE_DIRECTIVE_RULES.get(kind, []))

    draft = state.get("appointment_draft") or {}
    name = draft.get(AppointmentField.NAME.value)

    if (
        any(d.get("kind") == DirectiveKind.INFORM_SCHEDULED for d in directives)
        and _has_value(name)
    ):
        rules.append(
            f'The appointment is booked under the name "{name}".'
        )

    return rules


async def node_directive_prompt_builder(state: CallState):
    directives = state.get("directives") or []
    logger.warning(f"directives: {directives}")

    field_rules = _build_field_rules(state, directives)
    informative_rules = _build_informative_rules(state, directives)

    rules = informative_rules + field_rules

    return {
        "node_data": {
            "directive_prompt_builder": {
                "rules": rules,
                "active_fields": [d["field"] for d in directives if d.get("field")],
                "active_kinds": [d["kind"] for d in directives if d.get("kind")],
            }
        }
    }