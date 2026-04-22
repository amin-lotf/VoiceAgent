from __future__ import annotations

import json

from langchain_core.messages import SystemMessage, HumanMessage
from voice_agent.const import JSON_SENTINEL, NOT_SPECIFIED
from voice_agent.core.prompts.basic_info_extractor_blocks import get_extractor_rules
from voice_agent.core.prompts.global_blocks import GLOBAL_OPERATOR_RULES, OFFICE_INFO_RULES, OUT_OF_SCOPE_RULES, \
    CAPABILITY_EXPLANATION_RULES, JSON_RULES, OFFICE_INFO, build_assistant_intent_rules
from voice_agent.core.prompts.output_schemas import OPERATOR_OUTPUT_SCHEMA, INFO_EXTRACTOR_OUTPUT_SCHEMA
from voice_agent.core.prompts.user_info_blocks import get_collecting_info_rules
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


def _get_recent_messages(state: CallState) -> list[dict]:
    messages = state.get("messages") or []
    if not isinstance(messages, list):
        return []
    return messages


def build_basic_info_extractor_prompt(state):
    recent_messages = _get_recent_messages(state)
    all_rules = get_extractor_rules()

    system = f"""
You are an information extractor for a clinic call assistant.

Rules:
{chr(10).join("- " + r for r in all_rules)}

Output schema:
{INFO_EXTRACTOR_OUTPUT_SCHEMA}

""".strip()

    human = f"""
Active Conversation:
{_format_messages(recent_messages)}

""".strip()

    return [
        SystemMessage(content=system),
        HumanMessage(content=human),
    ]
