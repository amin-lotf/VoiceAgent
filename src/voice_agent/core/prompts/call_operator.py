from __future__ import annotations

import json
from langchain_core.messages import SystemMessage, HumanMessage
from voice_agent.const import JSON_SENTINEL, NOT_SPECIFIED
from voice_agent.core.graph.nodes.utils import get_state_data
from voice_agent.core.prompts.booking_appointment_blocks import get_book_appointment_rules
from voice_agent.core.prompts.collecting_notes_blocks import get_collecting_notes_rules
from voice_agent.core.prompts.global_blocks import GLOBAL_OPERATOR_RULES, OFFICE_INFO_RULES, OUT_OF_SCOPE_RULES, \
    CAPABILITY_EXPLANATION_RULES, JSON_RULES, OFFICE_INFO, build_assistant_intent_rules
from voice_agent.core.prompts.output_schemas import OPERATOR_OUTPUT_SCHEMA
from voice_agent.core.prompts.user_info_blocks import get_collecting_info_rules
from voice_agent.core.prompts.user_intent_blocks import get_user_intent_rules
from voice_agent.core.prompts.confirm_slot_blocks  import get_slot_confirmation_rules
from voice_agent.core.prompts.utils import extend_prompt_section, format_offered_time_for_voice, format_notes_for_prompt
from voice_agent.core.prompts.verify_info_blocks import get_verification_rules
from voice_agent.core.types import CallState, AppointmentStatus, AssistantPhase, FieldChange
import logging
from typing import Optional
from voice_agent.core.types import AppointmentDraft

logger = logging.getLogger(__name__)





def build_field_changes_prompt(changes: list[FieldChange]) -> str:
    if not changes:
        return ""

    lines: list[str] = ["Recent updates:"]

    for change in changes:
        field = change.get("field")
        old = change.get("old_value")
        new = change.get("new_value")
        action = change.get("action")

        if action == "added":
            lines.append(f'- {field}: "{new}"')
        elif action == "updated":
            lines.append(f'- {field}: "{old}" → "{new}"')

    return "\n".join(lines)


def format_appointment_info(draft: Optional[AppointmentDraft]) -> str:
    if not draft:
        return "Current appointment information:\nnone"

    name = draft.get("name") or "not provided"
    phone = draft.get("phone") or "not provided"
    reason = draft.get("reason_for_visit") or "not provided"

    # Prefer natural user text over ISO
    requested_time = draft.get("requested_time_text")
    if not requested_time:
        requested_time = draft.get("requested_time_iso")

    requested_time = requested_time or "not provided"

    return (
        "Current appointment information:\n"
        f"- Name: {name}\n"
        f"- Phone: {phone}\n"
        f"- Reason for visit: {reason}\n"
        f"- Requested time: {requested_time}"
    )






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







def build_operator_prompt(state, *, internal_call: bool = False):

    user_text = (state.get("user_text") or "").strip()
    recent_messages = _get_recent_messages(state)
    appointment_draft:AppointmentDraft = state.get("appointment_draft") or {}
    appointment_info = format_appointment_info(appointment_draft)
    recent_changes = ""
    all_rules = []
    extend_prompt_section(all_rules, "Global operator", GLOBAL_OPERATOR_RULES)



    if internal_call:
       pass
    else:
        extend_prompt_section(all_rules, "Office info rules", OFFICE_INFO_RULES)
        extend_prompt_section(all_rules, "Office info rules", build_assistant_intent_rules())
        extend_prompt_section(all_rules, "Out of scope rules", OUT_OF_SCOPE_RULES)
        extend_prompt_section(all_rules, "Capability explanation rules", CAPABILITY_EXPLANATION_RULES)

    assistant_phase = state.get("assistant_phase")
    if not assistant_phase:
        raise ValueError("No assistant phase in state")

    output_schema = OPERATOR_OUTPUT_SCHEMA.get(assistant_phase, {})
    if not output_schema:
        raise ValueError(f"Undefined output schema for current phase: {assistant_phase}")

    output_schema_text = json.dumps(output_schema, ensure_ascii=True, indent=2)

    match assistant_phase:
        case AssistantPhase.COLLECTING_USER_INTENT:
            all_rules.extend(get_user_intent_rules())
        case AssistantPhase.COLLECTING_INFO:
            all_rules.extend(get_collecting_info_rules())
        case AssistantPhase.VERIFYING_INFO:
            all_rules.extend(get_verification_rules())
            basic_info_node= get_state_data(state, "basic_info")
            field_changes= basic_info_node.get("field_changes") or []
            recent_changes = build_field_changes_prompt(field_changes)
        case AssistantPhase.CONFIRMING_SLOT:
            all_rules.extend(get_slot_confirmation_rules())
            recent_changes = format_offered_time_for_voice(appointment_draft.get('last_offered_slot_start_at'))
        case AssistantPhase.BOOKING_APPOINTMENT:
            all_rules.extend(get_book_appointment_rules())
        case AssistantPhase.COLLECTING_NOTES:
            all_rules.extend(get_collecting_notes_rules())
            recent_changes = format_notes_for_prompt(appointment_draft.get('notes') or [])
        case _:
            raise ValueError(f"Undefined assistant phase: {assistant_phase}")




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

Updated information:
{recent_changes or "none"}


Caller Now:
{user_text or "none" if not internal_call else "none"}

{appointment_info}

""".strip()

    return [
        SystemMessage(content=system),
        HumanMessage(content=human),
    ]
