from __future__ import annotations

import json

from langchain_core.messages import SystemMessage, HumanMessage
from voice_agent.const import JSON_SENTINEL, NOT_SPECIFIED
from voice_agent.core.prompts.global_blocks import GLOBAL_OPERATOR_RULES, OFFICE_INFO_RULES, OUT_OF_SCOPE_RULES, \
    CAPABILITY_EXPLANATION_RULES, JSON_RULES, OFFICE_INFO
from voice_agent.core.prompts.output_schemas import OPERATOR_OUTPUT_SCHEMA
from voice_agent.core.prompts.user_intent_blocks import get_user_intent_rules
from voice_agent.core.prompts.utils import extend_prompt_section
from voice_agent.core.types import CallState, AppointmentStatus, AssistantPhase
import logging

logger = logging.getLogger(__name__)











def _format_messages(messages: list[dict]) -> str:
    if not messages:
        return "none"

    lines: list[str] = []
    for m in messages:
        role = (m.get("role") or "unknown").strip()
        content = (m.get("content") or "").strip()
        if content:
            lines.append(f"{role}: {content}")

    return "\n".join(lines) if lines else "none"


def _get_recent_messages(state: CallState, limit: int = 8) -> list[dict]:
    messages = state.get("messages") or []
    if not isinstance(messages, list):
        return []
    return messages[-limit:]







def build_operator_prompt(state, *, internal_call: bool = False):

    user_text = (state.get("user_text") or "").strip()
    recent_messages = _get_recent_messages(state, limit=8)

    all_rules = []
    extend_prompt_section(all_rules, "Global operator", GLOBAL_OPERATOR_RULES)
    extend_prompt_section(all_rules, "Office info rules", OFFICE_INFO_RULES)

    if internal_call:
       pass
    else:
        assistant_phase = state.get("assistant_phase")
        if not assistant_phase:
            raise ValueError("No assistant phase in state")

        output_schema = OPERATOR_OUTPUT_SCHEMA[assistant_phase]

        output_schema_text = json.dumps(output_schema, ensure_ascii=True, indent=2)

        match assistant_phase:
            case AssistantPhase.COLLECTING_USER_INTENT:

                all_rules.extend(get_user_intent_rules())

        extend_prompt_section(all_rules, "Out of scope rules", OUT_OF_SCOPE_RULES)
        extend_prompt_section(all_rules, "Capability explanation rules", CAPABILITY_EXPLANATION_RULES)
        extend_prompt_section(all_rules, "JSON rules", JSON_RULES)





        system = f"""
You are a clinic call assistant.

Rules:
{chr(10).join("- " + r for r in all_rules)}




Output schema:
{output_schema_text}

office_knowledge:
{OFFICE_INFO}

Format:
Reply text first.
Then {JSON_SENTINEL}
Then JSON.
""".strip()

        human = f"""
Active Conversation:
{_format_messages(recent_messages)}


Caller Now:
{user_text or "none"}



""".strip()

    return [
        SystemMessage(content=system),
        HumanMessage(content=human),
    ]
