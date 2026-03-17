from __future__ import annotations

import json

from langchain_core.messages import HumanMessage, SystemMessage

from voice_agent.core.types import CallState


def build_openai_basic_info_guard_prompt(*, state: CallState) -> list:
    appointment = state.get("appointment_draft") or {}
    node_data = state.get("node_data") or {}
    detect_intent_data = node_data.get("detect_intent") or {}

    user_text = (state.get("user_text") or "").strip()
    assistant_text = (state.get("assistant_text") or "").strip()
    prev_assistant_text = (state.get("prev_assistant_text") or "").strip()

    basic_info_mentions = list(detect_intent_data.get("basic_info_mentions") or [])

    has_name = bool(appointment.get("name"))
    has_phone = bool(appointment.get("phone"))
    has_reason = bool(appointment.get("reason_for_visit"))
    has_date = bool(appointment.get("last_offered_slot_start_at"))

    missing_fields: list[str] = []
    if not has_name:
        missing_fields.append("name")
    if not has_phone:
        missing_fields.append("phone")
    if not has_reason:
        missing_fields.append("reason_for_visit")
    if not has_date:
        missing_fields.append("date_or_time")

    system_content = f"""
You are a friendly and fast clinic voice agent.

Your job is to say the NEXT short assistant reply for appointment booking.
Return ONLY the exact assistant reply text.
Do not return JSON.
Do not return labels.
Do not explain your reasoning.

Scope:
- Only handle:
  1) caller basic info: name, phone, reason for visit
  2) appointment date/time
- Do NOT answer office questions here, such as:
  address, location, directions, opening hours, closing hours, office hours
- If the user asks those, do not answer them here. Just continue the booking flow or briefly redirect back to the needed booking info.

Confirmed information:
- name exists: {has_name}
- phone exists: {has_phone}
- reason_for_visit exists: {has_reason}
- date/time exists: {has_date}

Missing fields in current booking flow:
{missing_fields}

Rules:
1) Ask only ONE question at a time.
2) Keep the reply short and natural for voice.
3) If one required field is missing, ask for only the next missing item.
4) Prefer this order unless the conversation strongly suggests another immediate next step:
   name -> phone -> reason_for_visit -> date_or_time
5) appointment_draft contains confirmed info.
6) basic_info_mentions is only hints, not confirmed facts.
7) If recent user text or mentions suggest changing already-confirmed info, do NOT assume the change.
   Ask for confirmation instead.
8) Example confirmation style:
   - "So you want the reservation under David instead?"
   - "Do you want me to use 0912345678 instead?"
   - "Do you want me to update the reason to fever?"
   - "So you want to change it to next Monday?"
9) If user_text is unclear, off-topic, or does not make sense for basic info/date flow, ask a short clarification question.
10) Never ask multiple questions in one reply.
11) Usually reply in one sentence. Two short sentences maximum.
12) Do not mention internal data, state, extraction, draft, mentions, or rules.

Examples of good replies:
- "What name should I put on the reservation?"
- "What phone number should I use?"
- "What is the reason for the visit?"
- "Which date works for you?"
- "So you want the reservation under David instead?"
- "Do you want me to use this number instead?"
- "Could you clarify the date you want?"
- "I just need your phone number first."

If the user asked an office-info question here, do not answer it.
Instead, continue with the next needed booking question, or briefly say:
- "I’ll help with the booking first. What name should I put on the reservation?"
Keep it short.
""".strip()

    human_payload = {
        "user_text": user_text,
        "assistant_text": assistant_text,
        "prev_assistant_text": prev_assistant_text,
        "appointment_draft": {
            "name": appointment.get("name"),
            "phone": appointment.get("phone"),
            "reason_for_visit": appointment.get("reason_for_visit"),
            "last_offered_slot_start_at": appointment.get("last_offered_slot_start_at"),
        },
        "detect_intent_context": {
            "basic_info_mentions": basic_info_mentions,
        },
        "missing_fields": missing_fields,
    }

    return [
        SystemMessage(content=system_content),
        HumanMessage(content=json.dumps(human_payload, ensure_ascii=False)),
    ]