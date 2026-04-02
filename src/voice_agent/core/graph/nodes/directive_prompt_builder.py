from __future__ import annotations

from voice_agent.const import NOT_SPECIFIED
from voice_agent.core.types import CallState, AssistantDirective, AppointmentField, DirectiveKind
from voice_agent.core.prompts.operator_blocks import PATCH_FIELD_RULES, REQUESTING_FIELD_RULES, EXISTING_FIELD_RULES
import logging

logger = logging.getLogger(__name__)


def _has_value(v):
    return v not in (None, "", NOT_SPECIFIED)


def _build_missing_field_rules(state, directives: list[AssistantDirective]) -> list[str]:
    draft = state.get("appointment_draft") or {}
    rules: list[str] = []

    active_fields = {
        d.get("field") for d in directives if d.get("field")
                                              and d.get("kind") == DirectiveKind.REQUEST_MISSING_INFO
    }

    for field in PATCH_FIELD_RULES.keys():
        if field in active_fields:
            # rules.append(f"{field.value} is missing → ask for it.")
            rules.extend(REQUESTING_FIELD_RULES[field])
            continue

        if _has_value(draft.get(field.value)):
            # rules.append(f"{field.value} already exists → do not ask again unless user changes it.")
            rules.extend(EXISTING_FIELD_RULES[field])

    return rules


async def node_directive_prompt_builder(state):
    directives = state.get("directives") or []
    logger.warning(f"directives: {directives}")
    rules = _build_missing_field_rules(state, directives)

    return {
        "node_data": {
            "directive_prompt_builder": {
                "rules": rules,
                "active_fields": [d["field"] for d in directives if d.get("field")]
            }
        }
    }
