from __future__ import annotations

from voice_agent.const import NOT_SPECIFIED
from voice_agent.core.types import (
    CallState,
    AssistantDirective,
    AppointmentField,
    DirectiveKind, ConfirmationTopic,
)
from voice_agent.core.prompts.operator_blocks import (
    PATCH_FIELD_RULES,
    REQUESTING_FIELD_RULES,
    EXISTING_FIELD_RULES,
    INFORMATIVE_DIRECTIVE_RULES, CONFIRMATION_RULES,
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

    for field in AppointmentField:
        if field in active_fields:
            rules.extend(REQUESTING_FIELD_RULES[field])
            continue

        if _has_value(draft.get(field.value)):
            if EXISTING_FIELD_RULES.get(field):
                rules.extend(EXISTING_FIELD_RULES[field])

    return rules

def _build_confirmation_rules(
    state: CallState,
    directives: list[AssistantDirective],
) -> list[str]:
    rules: list[str] = []
    active_confirmations = {
        d.get("confirmation_topic")
        for d in directives
        if d.get("confirmation_topic") and d.get("kind") == DirectiveKind.REQUEST_CONFIRMATION
    }
    draft = state.get("appointment_draft") or {}
    slot_iso = draft.get("last_offered_slot_start_at")

    for confirmation_topic in ConfirmationTopic:
        if confirmation_topic in active_confirmations:
            rules.extend(CONFIRMATION_RULES[confirmation_topic])
    if (
            any(d.get("confirmation_topic") == ConfirmationTopic.HOLD_CONFIRMATION for d in directives)
            and _has_value(slot_iso)
    ):
        rules.append(
            f'There is a slot available at "{slot_iso}".'
        )
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
    confirmation_rules = _build_confirmation_rules(state, directives)
    informative_rules = _build_informative_rules(state, directives)

    rules = confirmation_rules + informative_rules + field_rules

    return {
        "node_data": {
            "directive_prompt_builder": {
                "rules": rules,
                "active_fields": [d["field"] for d in directives if d.get("field")],
                "active_kinds": [d["kind"] for d in directives if d.get("kind")],
            }
        }
    }