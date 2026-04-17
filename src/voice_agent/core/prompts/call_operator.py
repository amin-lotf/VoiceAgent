from __future__ import annotations

from langchain_core.messages import SystemMessage, HumanMessage
from voice_agent.const import JSON_SENTINEL, NOT_SPECIFIED
from voice_agent.core.prompts.operator_blocks import *
from voice_agent.core.types import CallState, AppointmentStatus, DirectiveKind
import logging

logger = logging.getLogger(__name__)


QUESTION_DIRECTIVE_KINDS = {
    DirectiveKind.REQUEST_MISSING_INFO,
    DirectiveKind.REQUEST_CLARIFY_INFO,
    DirectiveKind.REQUEST_CONFIRMATION,
    DirectiveKind.REQUEST_USER_INTENT,
}




def _build_turn_scope_rules(state: CallState) -> list[str]:
    directives = state.get("directives") or []
    draft = state.get("appointment_draft") or {}

    has_open_question = any(
        d.get("kind") in QUESTION_DIRECTIVE_KINDS
        for d in directives
    )

    appointment_complete = draft.get("status") == AppointmentStatus.SCHEDULED

    if has_open_question:
        return OPEN_QUESTION_RULES

    if appointment_complete:
        return POST_BOOKING_NO_QUESTION_RULES

    return PRE_BOOKING_NO_QUESTION_RULES





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
    return messages[-limit:-2]


def _extend_section(rules: list[str], title: str, items: list[str]) -> None:
    if not items:
        return
    rules.append(f"[{title}]")
    rules.extend(items)





def _format_directives(directives: list[dict]) -> str:
    if not directives:
        return "none"

    lines: list[str] = []
    for idx, directive in enumerate(directives, start=1):
        parts = [f'kind="{directive.get("kind")}"']

        field = directive.get("field")
        if field:
            parts.append(f'field="{field}"')

        confirmation_topic = directive.get("confirmation_topic")
        if confirmation_topic:
            parts.append(f'confirmation_topic="{confirmation_topic}"')

        priority = directive.get("priority")
        if priority is not None:
            parts.append(f"priority={priority}")

        lines.append(f"{idx}. " + ", ".join(parts))

    return "\n".join(lines)


def build_operator_prompt(state, *, internal_call: bool = False):
    node_data = state.get("node_data") or {}
    directive_prompts = node_data.get("directive_prompt_builder", {}).get("rules", [])
    office_knowledge = node_data.get("office_info", {}).get("knowledge", {})

    appointment = state.get("appointment_draft") or {}
    appointment_status = appointment.get("status")
    directives = state.get("directives") or []
    user_text = (state.get("user_text") or "").strip()
    recent_messages = _get_recent_messages(state, limit=8)

    prev_assistant_text = (state.get("prev_assistant_text") or state.get("assistant_text") or "").strip()
    prev_user_text = (state.get("prev_user_text") or "").strip()

    global_rules = GLOBAL_OPERATOR_RULES + _build_turn_scope_rules(state)
    all_rules = []
    _extend_section(all_rules, "Global operator", global_rules)
    if internal_call:
        _extend_section(all_rules, "Internal follow-up", INTERNAL_CALL_RULES)
    _extend_section(all_rules, "Directive prompt rules", directive_prompts)

    if internal_call:
        output_schema = {
            "end_call": False,
        }
        _extend_section(all_rules, "JSON", JSON_RULES)

        system = f"""
You are a clinic call assistant.

Rules:
{chr(10).join("- " + r for r in all_rules)}


Output schema:
{output_schema}

Format:
Reply text first.
Then {JSON_SENTINEL}
Then JSON.
""".strip()

        human = f"""



Task:
Generate the next assistant reply for the current directives.
Continue from the ongoing conversation.
There is no new caller message to interpret in this turn.
If a directive still requires one question, ask it directly now.
Do not greet, thank, or restart the conversation.



Previous caller text:
{prev_user_text or "none"}

Previous assistant text:
{prev_assistant_text or "none"}

Current directives:
{_format_directives(directives)}
""".strip()

    else:
        output_schema = {
            "clinic_intent": "continue",
            "user_intent": NOT_SPECIFIED,
            "end_call": False,
            "patch": {
                "name": NOT_SPECIFIED,
                "phone": NOT_SPECIFIED,
                "reason_for_visit": NOT_SPECIFIED,
                "notes": [],
            },
            "datetime_detected": False,
            "confirmation_intent": NOT_SPECIFIED,
        }

        _extend_section(all_rules, "Clinic intent", CLINIC_INTENT_RULES)
        _extend_section(all_rules, "Datetime", DATETIME_RULES)
        _extend_section(all_rules, "Office info", OFFICE_INFO_RULES)
        if appointment_status == AppointmentStatus.HELD:
            _extend_section(all_rules, "Confirmation intent", CONFIRMATION_INTENT_RULES)
        _extend_section(all_rules, "User intent", USER_INTENT_RULES)
        _extend_section(all_rules, "Out of scope", OUT_OF_SCOPE_RULES)
        _extend_section(all_rules, "Capability explanation", CAPABILITY_EXPLANATION_RULES)
        if appointment_status == AppointmentStatus.SCHEDULED:
            _extend_section(all_rules, "Post-booking closing", POST_BOOKING_CLOSING_RULES)


        turn_local_rules = [
            "For JSON extraction fields, Caller Now is the only source of truth.",
            "Do not use Recent message history or Current draft to set patch fields, datetime_detected, confirmation_intent, or user_intent.",
            f"If Caller Now is empty, set datetime_detected=false, confirmation_intent={NOT_SPECIFIED}, user_intent={NOT_SPECIFIED}, and keep patch fields as NOT_SPECIFIED/empty.",
        ]
        _extend_section(all_rules, "Turn-local extraction", turn_local_rules)

        patch_rules: list[str] = []
        for field_rules in PATCH_FIELD_RULES.values():
            patch_rules.extend(field_rules)
        _extend_section(all_rules, "Patch extraction", patch_rules)
        _extend_section(all_rules, "JSON", JSON_RULES)

        system = f"""
You are a clinic call assistant.

Rules:
{chr(10).join("- " + r for r in all_rules)}




Output schema:
{output_schema}

office_knowledge:
{office_knowledge}

Format:
Reply text first.
Then {JSON_SENTINEL}
Then JSON.
""".strip()

        human = f"""
Recent message history:
{_format_messages(recent_messages)}

Previous assistant text:
{prev_assistant_text or "none"}

Caller Now:
{user_text or "none"}

Current directives:
{_format_directives(directives)}


""".strip()

    return [
        SystemMessage(content=system),
        HumanMessage(content=human),
    ]
