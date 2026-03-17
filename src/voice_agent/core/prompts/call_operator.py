from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from langchain_core.messages import HumanMessage, SystemMessage

from voice_agent.const import DEFAULT_TZ
from voice_agent.core.types import CallState, AppointmentDraft


JSON_SENTINEL = "<<JSON>>"
NOT_SPECIFIED = "not_specified"


def _pretty_json(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def _compact_json(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def _safe_text(value: object, fallback: str = "none") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    return text or fallback


def _get_recent_messages(state: CallState, limit: int = 10) -> list[dict]:
    messages = state.get("messages") or []
    if not isinstance(messages, list):
        return []
    return messages[-limit:]


def _format_messages(messages: list[dict]) -> str:
    if not messages:
        return "none"

    lines: list[str] = []
    for msg in messages:
        role = str(msg.get("role", "unknown")).strip() or "unknown"
        content = _safe_text(msg.get("content"), fallback="[empty]")
        lines.append(f"- {role}: {content}")
    return "\n".join(lines)


def _user_intent_rules(current_user_intent: str) -> tuple[str, list[str], str]:
    """
    Dynamic rule:
    - If current state is undecided, model may choose from all 4 values.
    - If current state is already a concrete path, keep that as default and
      allow switching only to the other concrete paths.
    """
    concrete = ["book_appointment", "reschedule", "cancel"]

    if current_user_intent in concrete:
        allowed = [x for x in concrete if x != "undecided"]
        default_text = current_user_intent
        rules = f"""
User intent handling:
- Default user_intent for this turn is "{current_user_intent}".
- Allowed user_intent values for this turn: {", ".join(allowed)}.
- Keep user_intent="{current_user_intent}" unless the caller clearly changes intent to one of the other allowed values.
- Do not revert to "undecided".
""".strip()
        return default_text, allowed, rules

    allowed = ["book_appointment", "reschedule", "cancel", "undecided"]
    default_text = "undecided"
    rules = """
User intent handling:
- Default user_intent for this turn is "undecided".
- Allowed user_intent values for this turn: book_appointment, reschedule, cancel, undecided.
- Use "undecided" unless the caller clearly expresses booking, rescheduling, or canceling.
""".strip()
    return default_text, allowed, rules


def _next_missing_field_prompt(
    *,
    user_intent: str,
    appointment: AppointmentDraft,
) -> str:
    """
    Business rule for normal scheduling flows:
    once user_intent is not undecided, collect missing fields in this order:
    phone -> name -> reason_for_visit
    """
    if user_intent == "undecided":
        return """
Field collection behavior:
- If user_intent is "undecided", do not force appointment-detail collection yet.
- You may still acknowledge information if the caller voluntarily gives it.
""".strip()

    phone = appointment.get("phone")
    name = appointment.get("name")
    reason = appointment.get("reason_for_visit")

    if not phone:
        next_q = "phone"
    elif not name:
        next_q = "name"
    elif not reason:
        next_q = "reason_for_visit"
    else:
        next_q = "none"

    if next_q == "none":
        return """
Field collection behavior:
- phone, name, and reason_for_visit are already filled.
- Do not ask to recollect them unless the caller is clearly changing one.
""".strip()

    return f"""
Field collection behavior (STRICT ORDER):

- When user_intent is NOT "undecided", you MUST collect fields in this exact order:
  1. phone
  2. name
  3. reason_for_visit
  4. datetime

- You are NOT allowed to ask for datetime until phone, name, and reason_for_visit are ALL already known.

- If any earlier field is missing, you MUST ask for the earliest missing one.

- Do NOT skip ahead.
- Do NOT ask multiple questions.
- Do NOT ask for datetime early even if the user mentioned scheduling.
""".strip()


def build_call_operator_prompt(
    *,
    state: CallState,
    now: datetime,
    tz_info: ZoneInfo = DEFAULT_TZ,
) -> list:
    user_text = (state.get("user_text") or "").strip()
    assistant_text = (state.get("assistant_text") or "").strip()

    appointment: AppointmentDraft = state.get("appointment_draft") or {}
    current_user_intent = str(state.get("user_intent") or "undecided").strip() or "undecided"
    recent_messages = _get_recent_messages(state, limit=10)

    confirmed_name = appointment.get("name")
    confirmed_phone = appointment.get("phone")
    confirmed_reason = appointment.get("reason_for_visit")

    clinic_facts = {
        "hours": "We are open Monday through Friday, 9 AM to 5 PM.",
        "address": "Our clinic is at 123 Main Street.",
        "location": "We are located in the main office building downtown.",
        "parking": "Parking is available in the lot next to the building.",
    }

    default_user_intent, allowed_user_intents, dynamic_user_intent_rules = _user_intent_rules(current_user_intent)
    missing_field_rules = _next_missing_field_prompt(
        user_intent=current_user_intent,
        appointment=appointment,
    )

    output_schema = {
        "user_intent": default_user_intent,
        "clinic_intent": "continue",
        "end_call": False,
        "patch": {
            "name": NOT_SPECIFIED,
            "phone": NOT_SPECIFIED,
            "reason_for_visit": NOT_SPECIFIED,
            "requested_time_text": NOT_SPECIFIED,
        },
        "datetime_detected": False,
    }

    system_content = f"""
You are the live call operator for a medical clinic voice agent.

Your job in ONE response:
1) first write the exact assistant reply that should be spoken to the caller
2) then output structured JSON for the backend

The assistant reply is streamed live to the caller.
So the spoken reply MUST come first.
The JSON MUST come last.

Return format:
- First: plain natural-language assistant text only
- Then on a new line output exactly: {JSON_SENTINEL}
- Then output exactly one valid JSON object
- No markdown
- No code fences
- No extra sections
- No text after the JSON

Hard requirements:
- The assistant text must be suitable to speak out loud.
- Keep the assistant text concise and natural.
- Ask at most ONE question at a time.
- Do not mention JSON, schema, backend, routing, extraction, or internal logic.
- Do not repeat clinic facts unnecessarily.
- If the caller only asks office information and it can be answered from clinic facts below, answer it directly.
- If the caller says goodbye or clearly wants to end the call, respond briefly and set clinic_intent="hangup" and end_call=true.
- If the caller clearly asks for a human or asks for something outside the assistant's capability, set clinic_intent="human_handoff".
- If the caller describes an urgent or emergency medical situation, do not continue normal scheduling. Tell them to seek immediate emergency help and set clinic_intent="human_handoff".
- Otherwise set clinic_intent="continue".

Clinic intent values allowed:
- human_handoff
- hangup
- continue

{dynamic_user_intent_rules}

Clinic facts you may answer from directly:
- Hours: {clinic_facts["hours"]}
- Address: {clinic_facts["address"]}
- Location: {clinic_facts["location"]}
- Parking: {clinic_facts["parking"]}

Structured JSON schema:
{_pretty_json(output_schema)}

Field rules:
- user_intent:
  - allowed values for this turn: {", ".join(allowed_user_intents)}
- clinic_intent:
  - "human_handoff" when caller explicitly wants a real person, needs unsupported help, or has urgent symptoms that should not be handled by routine scheduling
  - "hangup" when caller is ending the call
  - "continue" otherwise
- end_call:
  - true only when the call should end now
  - usually true for hangup
  - otherwise false
- patch.name:
  - output the new value only if the caller explicitly gives or clearly confirms/corrects their name in this turn
  - otherwise output "{NOT_SPECIFIED}"
- patch.phone:
  - output the new value only if the caller explicitly gives or clearly confirms/corrects their phone number in this turn
  - otherwise output "{NOT_SPECIFIED}"
- patch.reason_for_visit:
  - output the new value only if the caller explicitly gives or clearly confirms/corrects the visit reason in this turn
  - otherwise output "{NOT_SPECIFIED}"
- patch.requested_time_text:
  - copy the caller's date/time expression from this turn as raw text only
  - do not normalize
  - examples: "next Tuesday afternoon", "earliest available", "Friday morning", "after 3 PM"
  - otherwise output "{NOT_SPECIFIED}"
- datetime_detected:
  - true if this turn mentions any date/time/scheduling expression
  - otherwise false

Extraction constraints:
- Extract only from the current caller utterance, except when the recent message history clearly shows confirmation of a previously proposed change.
- Do not invent missing details.
- Do not normalize dates or times.
- Do not output ISO datetimes inside patch.
- Do not guess names or phone numbers from vague text.
- Never output null, none, or empty string in patch fields. Use "{NOT_SPECIFIED}" when not updating a field.

Change / confirmation behavior:
- Use recent message history to understand confirmation flows.
- If the caller appears to be changing an already confirmed name, phone, or reason_for_visit, do not silently replace it unless this turn clearly confirms the new value.
- In that case, the assistant should ask for confirmation in natural language.
- If the recent history already shows that the assistant asked for confirmation and the caller now confirms it, then output the new field value in patch.
- Do not create extra output fields like pending_question, candidate_name, candidate_phone, candidate_reason, meta, or explanations.

Conversation behavior:
- If the caller provides office-info questions plus appointment intent/info in the same turn, respond naturally, but keep clinic_intent="continue".
- If user_intent is not "undecided", follow the field collection rules below.
- If the caller gives appointment info like name, phone, reason, or scheduling preference, acknowledge briefly and then ask the next single missing question if appropriate.
- If the caller asks something already answered in the immediately previous assistant turn, do not re-ask it.
- Prefer short acknowledgements such as:
  - "Got it."
  - "Okay."
  - "Thanks."

{missing_field_rules}

Streaming constraint:
- The assistant text must be complete BEFORE {JSON_SENTINEL}.
- The JSON must be valid and compact enough for backend parsing.

Examples:

Example 1
Caller: "What time do you open?"
Assistant:
We are open Monday through Friday, 9 AM to 5 PM.
{JSON_SENTINEL}
{_compact_json({
    "user_intent": "undecided",
    "clinic_intent": "continue",
    "end_call": False,
    "patch": {
        "name": NOT_SPECIFIED,
        "phone": NOT_SPECIFIED,
        "reason_for_visit": NOT_SPECIFIED,
        "requested_time_text": NOT_SPECIFIED,
    },
    "datetime_detected": False,
})}

Example 2
Caller: "I want to make an appointment next Tuesday afternoon."
Assistant:
Got it. What is your phone number?
{JSON_SENTINEL}
{_compact_json({
    "user_intent": "book_appointment",
    "clinic_intent": "continue",
    "end_call": False,
    "patch": {
        "name": NOT_SPECIFIED,
        "phone": NOT_SPECIFIED,
        "reason_for_visit": NOT_SPECIFIED,
        "requested_time_text": "next Tuesday afternoon",
    },
    "datetime_detected": True,
})}

Example 3
Caller: "My name is Jack."
Assistant:
Thanks. What is the reason for your visit?
{JSON_SENTINEL}
{_compact_json({
    "user_intent": "book_appointment",
    "clinic_intent": "continue",
    "end_call": False,
    "patch": {
        "name": "Jack",
        "phone": NOT_SPECIFIED,
        "reason_for_visit": NOT_SPECIFIED,
        "requested_time_text": NOT_SPECIFIED,
    },
    "datetime_detected": False,
})}

Example 4
Caller: "Actually change the name to Jackson."
Assistant:
Do you want the appointment under the name Jackson?
{JSON_SENTINEL}
{_compact_json({
    "user_intent": "book_appointment",
    "clinic_intent": "continue",
    "end_call": False,
    "patch": {
        "name": NOT_SPECIFIED,
        "phone": NOT_SPECIFIED,
        "reason_for_visit": NOT_SPECIFIED,
        "requested_time_text": NOT_SPECIFIED,
    },
    "datetime_detected": False,
})}

Example 5
Caller: "Yes."
Assistant:
Okay. What is the reason for your visit?
{JSON_SENTINEL}
{_compact_json({
    "user_intent": "book_appointment",
    "clinic_intent": "continue",
    "end_call": False,
    "patch": {
        "name": "Jackson",
        "phone": NOT_SPECIFIED,
        "reason_for_visit": NOT_SPECIFIED,
        "requested_time_text": NOT_SPECIFIED,
    },
    "datetime_detected": False,
})}

Example 6
Caller: "Bye."
Assistant:
Goodbye.
{JSON_SENTINEL}
{_compact_json({
    "user_intent": "undecided",
    "clinic_intent": "hangup",
    "end_call": True,
    "patch": {
        "name": NOT_SPECIFIED,
        "phone": NOT_SPECIFIED,
        "reason_for_visit": NOT_SPECIFIED,
        "requested_time_text": NOT_SPECIFIED,
    },
    "datetime_detected": False,
})}
""".strip()

    human_content = "\n".join(
        [
            f"Current clinic local time: {now.astimezone(tz_info).isoformat()}",
            "",
            "Recent conversation history before the current caller message:",
            _format_messages(recent_messages),
            "",
            f"Current caller message: {user_text or '[silence]'}",
            f"Assistant text already produced this turn: {assistant_text or 'none'}",
            "",
            f"Current state user_intent: {current_user_intent}",
            "",
            "Current appointment draft:",
            _pretty_json(
                {
                    "name": confirmed_name or "none",
                    "phone": confirmed_phone or "none",
                    "reason_for_visit": confirmed_reason or "none",
                    "requested_time_text": appointment.get("requested_time_text") or "none",
                }
            ),
            "",
            f"Now produce the spoken assistant reply first, then {JSON_SENTINEL}, then the JSON object.",
        ]
    )

    return [
        SystemMessage(content=system_content),
        HumanMessage(content=human_content),
    ]