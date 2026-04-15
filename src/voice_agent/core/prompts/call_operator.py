from __future__ import annotations

from langchain_core.messages import SystemMessage, HumanMessage
from voice_agent.const import JSON_SENTINEL, NOT_SPECIFIED
from voice_agent.core.prompts.operator_blocks import *
from voice_agent.core.types import CallState, AppointmentStatus
import logging

logger = logging.getLogger(__name__)


def _build_no_question_rules(state: CallState) -> list[str]:
    directives = state.get("directives") or []
    draft = state.get("appointment_draft") or {}

    has_open_question = any(
        d.get("kind") in {
            DirectiveKind.REQUEST_MISSING_INFO,
            DirectiveKind.REQUEST_CONFIRMATION,
        }
        for d in directives
    )

    appointment_complete = draft.get("status") == AppointmentStatus.SCHEDULED

    if not has_open_question and appointment_complete:
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
    return messages[-limit:]


def _extend_section(rules: list[str], title: str, items: list[str]) -> None:
    if not items:
        return
    rules.append(f"[{title}]")
    rules.extend(items)


def _format_draft_summary(draft: dict) -> str:
    if not draft:
        return "none"

    summary = {
        "name_present": bool(draft.get("name")),
        "phone_present": bool(draft.get("phone")),
        "reason_present": bool(draft.get("reason_for_visit")),
        "notes_count": len(draft.get("notes") or []),
        "requested_time_present": bool(draft.get("requested_time_text") or draft.get("requested_time_iso")),
        "offered_time_confirmed": bool(draft.get("offered_time_confirmed")),
        "status": str(draft.get("status")) if draft.get("status") is not None else None,
    }
    return str(summary)


def build_operator_prompt(state, *, internal_call: bool = False):
    node_data = state.get("node_data") or {}
    directive_prompts = node_data.get("directive_prompt_builder", {}).get("rules", [])
    office_knowledge = node_data.get("office_info", {}).get("knowledge", {})

    appointment = state.get("appointment_draft") or {}
    user_text = (state.get("user_text") or "").strip()
    recent_messages = _get_recent_messages(state, limit=8)

    prev_assistant_text = state.get("assistant_text") or ""
    prev_user_text = state.get("user_text") or ""

    global_rules = GLOBAL_OPERATOR_RULES + _build_no_question_rules(state)
    all_rules = []
    _extend_section(all_rules, "Global operator", global_rules)
    _extend_section(all_rules, "Directive prompt rules", directive_prompts)
    _extend_section(all_rules, "JSON", JSON_RULES)

    if internal_call:
        output_schema = {
            "end_call": False,
        }

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

Current draft:
{_format_draft_summary(appointment)}

Task:
Generate the next assistant reply for the current directives.
This is an internal transition. There is no new caller message to interpret.
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
        _extend_section(all_rules, "Confirmation intent", CONFIRMATION_INTENT_RULES)
        _extend_section(all_rules, "User intent", USER_INTENT_RULES)
        _extend_section(all_rules, "Out of scope", OUT_OF_SCOPE_RULES)
        _extend_section(all_rules, "Capability explanation", CAPABILITY_EXPLANATION_RULES)
        _extend_section(all_rules, "Post-booking closing", POST_BOOKING_CLOSING_RULES)


        turn_local_rules = [
            "For JSON extraction fields, Caller Now is the only source of truth.",
            "Do not use Recent message history or Current draft to set patch fields, datetime_detected, confirmation_intent, or user_intent.",
            f"If Caller Now is empty, set datetime_detected=false, confirmation_intent={NOT_SPECIFIED}, user_intent={NOT_SPECIFIED}, and keep patch fields as NOT_SPECIFIED/empty.",
        ]
        _extend_section(all_rules, "Turn-local extraction", turn_local_rules)

        for field_rules in PATCH_FIELD_RULES.values():
            all_rules.extend(field_rules)

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

Previous Caller reply:
{prev_user_text}

Previous assistant text:
{prev_assistant_text}

Caller Now:
{user_text or "none"}

Current draft:
{_format_draft_summary(appointment)}
""".strip()

    return [
        SystemMessage(content=system),
        HumanMessage(content=human),
    ]