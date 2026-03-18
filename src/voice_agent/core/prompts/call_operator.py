from __future__ import annotations

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from langchain_core.messages import HumanMessage, SystemMessage

from voice_agent.const import DEFAULT_TZ
from voice_agent.core.types import AppointmentDraft, CallState

JSON_SENTINEL = "###JSON###"
NOT_SPECIFIED = "NOT_SPECIFIED"


def _pretty_json(data: object) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def _format_messages(messages: list[dict]) -> str:
    if not messages:
        return "none"

    lines: list[str] = []
    for m in messages:
        role = (m.get("role") or "unknown").strip()
        content = (m.get("content") or "").strip()
        if not content:
            continue
        lines.append(f"{role}: {content}")

    return "\n".join(lines) if lines else "none"


def _get_recent_messages(state: CallState, limit: int = 10) -> list[dict]:
    messages = state.get("messages") or []
    if not isinstance(messages, list):
        return []
    return messages[-limit:]


def _user_intent_rules(current_user_intent: str) -> tuple[str, list[str], str]:
    current_user_intent = (current_user_intent or "undecided").strip()

    if current_user_intent in {"book_appointment", "reschedule", "cancel"}:
        allowed = [current_user_intent, "undecided"]
        default_text = current_user_intent
        rules = f"""
User intent handling:
- Default user_intent for this turn is "{current_user_intent}".
- Allowed user_intent values for this turn: {", ".join(allowed)}.
- Keep user_intent as "{current_user_intent}" unless the caller clearly changes their intent.
- Use "undecided" only if the caller becomes unclear or withdraws the scheduling request.
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


def build_next_14_days(now: datetime, tz_info: ZoneInfo = DEFAULT_TZ) -> list[dict]:
    local_now = now.astimezone(tz_info)
    today = local_now.date()

    items: list[dict] = []

    for i in range(14):
        d = today + timedelta(days=i)
        weekday = d.strftime("%A")
        month = d.strftime("%B")
        day_num = d.day
        year = d.year

        tags: list[str] = []
        if i == 0:
            tags.append("today")
        elif i == 1:
            tags.append("tomorrow")

        if d.weekday() == 0 and 7 <= i <= 13:
            tags.append("beginning_of_next_week")
        elif d.weekday() == 4 and 7 <= i <= 13:
            tags.append("end_of_next_week")

        items.append(
            {
                "date_key": d.isoformat(),
                "spoken": f"{weekday} {month} {day_num} {year}",
                "tags": tags,
            }
        )

    return items


def get_next_required_field(
    *,
    user_intent: str,
    appointment: AppointmentDraft,
) -> str:
    if user_intent == "undecided":
        return "none"

    if not appointment.get("phone"):
        return "phone"
    if not appointment.get("name"):
        return "name"
    if not appointment.get("reason_for_visit"):
        return "reason_for_visit"
    return "date_time"


def _all_basic_info_collected(appointment: AppointmentDraft) -> bool:
    return bool(
        appointment.get("phone")
        and appointment.get("name")
        and appointment.get("reason_for_visit")
    )


def _build_collection_rules(
    *,
    user_intent: str,
    appointment: AppointmentDraft,
) -> str:
    current_step = get_next_required_field(
        user_intent=user_intent,
        appointment=appointment,
    )

    has_phone = bool(appointment.get("phone"))
    has_name = bool(appointment.get("name"))
    has_reason = bool(appointment.get("reason_for_visit"))
    basic_done = _all_basic_info_collected(appointment)

    if current_step == "none":
        return """
Collection behavior:
- The caller's scheduling intent is not yet clear.
- Do not force collection yet.
- You may still extract any clearly volunteered phone, name, reason_for_visit, or scheduling info from this turn.
- Ask at most ONE question.
- If you ask a question, it should only clarify the caller's main intent.
""".strip()

    rules: list[str] = [
        "Collection behavior:",
        "- Ask at most ONE question.",
        "- You may extract any clearly stated phone, name, reason_for_visit, or date/time info from the caller's utterance, even if you do not ask about it.",
        "- If the caller clearly corrects or replaces an already collected phone, name, or reason_for_visit, update patch with the new value.",
        "- Never ask again for a field that is already filled unless the caller is clearly changing it.",
    ]

    if not has_phone:
        rules.append('- Phone is missing. If you ask a question, ask only for the phone number.')
    else:
        rules.append('- Phone already exists. Do not ask for phone again unless the caller clearly changes it.')

    if not has_name:
        rules.append('- Name is missing. If phone is already filled and you ask a question, ask only for the full name.')
    else:
        rules.append('- Name already exists. Do not ask for name again unless the caller clearly changes it.')

    if not has_reason:
        rules.append('- Reason for visit is missing. If phone and name are already filled and you ask a question, ask only for the reason for the visit.')
    else:
        rules.append('- Reason for visit already exists. Do not ask for it again unless the caller clearly changes it.')

    if basic_done:
        rules.extend(
            [
                "- Phone, name, and reason_for_visit are already collected.",
                "- Date/time collection is now allowed.",
                '- If you ask a scheduling question, ask only for appointment date/time preference.',
            ]
        )
    else:
        rules.extend(
            [
                "- Do not start date/time collection yet.",
                "- Do not ask about appointment date or time until phone, name, and reason_for_visit are all filled.",
                "- If the caller volunteers date/time anyway, you may detect and extract it in JSON, but do not move the conversation to date/time yet.",
            ]
        )

    return "\n".join(rules)


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

    current_step = get_next_required_field(
        user_intent=current_user_intent,
        appointment=appointment,
    )
    collection_rules = _build_collection_rules(
        user_intent=current_user_intent,
        appointment=appointment,
    )

    basic_done = _all_basic_info_collected(appointment)
    next_14_days = build_next_14_days(now=now, tz_info=tz_info) if basic_done else None

    output_schema = {
        "user_intent": default_user_intent,
        "clinic_intent": "continue",
        "end_call": False,
        "current_step": current_step,
        "patch": {
            "name": NOT_SPECIFIED,
            "phone": NOT_SPECIFIED,
            "reason_for_visit": NOT_SPECIFIED,
        },
        "datetime_detected": False,
        "schedule_patch": {
            "date_mode": "not_specified",
            "date_key": NOT_SPECIFIED,
            "time_pref": "not_specified",
            "exact_time_text": NOT_SPECIFIED,
        },
    }

    date_rules = ""
    if basic_done and next_14_days:
        date_rules = f"""
Date/time rules:
- Date/time collection is allowed in this turn.
- Available date anchors for the next 14 days:
{_pretty_json(next_14_days)}

- schedule_patch.date_mode:
  - allowed values: not_specified, specific_day, earliest, this_week, next_week
  - use "specific_day" only when the caller's requested day clearly maps to one of the provided date_key values
  - use "earliest" for requests like "earliest", "first available", "soonest available"
  - use "this_week" for broad requests like "this week"
  - use "next_week" for broad requests like "next week"
  - otherwise use "not_specified"

- schedule_patch.date_key:
  - output one exact date_key from the provided 14-day list only when the caller clearly selected or mentioned that specific day
  - otherwise output "{NOT_SPECIFIED}"

- schedule_patch.time_pref:
  - allowed values: not_specified, morning, afternoon, exact_time
  - use "morning" for requests like "morning"
  - use "afternoon" for requests like "afternoon"
  - use "exact_time" only when caller gives a specific time such as "2 PM" or "2:30"
  - otherwise use "not_specified"

- schedule_patch.exact_time_text:
  - copy the exact time phrase only when schedule_patch.time_pref="exact_time"
  - otherwise output "{NOT_SPECIFIED}"

- If the caller gives an out-of-range or vague date, ask them to choose a specific day within the next two weeks.
""".strip()
    else:
        date_rules = f"""
Date/time rules:
- Date/time collection is NOT allowed yet because phone, name, and reason_for_visit are not all filled.
- Do not ask about date or time in this turn.
- If the caller mentions date/time anyway, set datetime_detected=true.
- Keep schedule_patch.date_mode="not_specified", schedule_patch.date_key="{NOT_SPECIFIED}", schedule_patch.time_pref="not_specified", and schedule_patch.exact_time_text="{NOT_SPECIFIED}" unless your backend intentionally wants volunteered date/time captured before the basic fields are done.
""".strip()

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

- current_step:
  - copy exactly this value: "{current_step}"
  - do not invent another value
  - allowed values: none, phone, name, reason_for_visit, date_time

- patch.name:
  - output the new value only if the caller explicitly gives or clearly confirms/corrects their name in this turn
  - otherwise output "{NOT_SPECIFIED}"

- patch.phone:
  - output the new value only if the caller explicitly gives or clearly confirms/corrects their phone number in this turn
  - otherwise output "{NOT_SPECIFIED}"

- patch.reason_for_visit:
  - output the new value only if the caller explicitly gives or clearly confirms/corrects the visit reason in this turn
  - otherwise output "{NOT_SPECIFIED}"

- datetime_detected:
  - true if this turn mentions any date/time/scheduling expression
  - otherwise false

{collection_rules}

{date_rules}

Speaking behavior:
- Sound natural, calm, and brief.
- If the caller already gave useful info in this turn, acknowledge it briefly before asking the next question.
- Never ask for the same field again if it was clearly provided in this turn.
- If office info is asked together with scheduling info, answer briefly and then continue with the single allowed next question.
""".strip()

    human_content = "\n".join(
        [
            f"Current clinic local time: {now.astimezone(tz_info).isoformat()}",
            f"Caller now: {user_text or '[silence]'}",
            f"Assistant text already produced this turn: {assistant_text or 'none'}",
            "",
            f"Current state user_intent: {current_user_intent}",
            f"Current required step: {current_step}",
            f"Basic info complete: {basic_done}",
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
            "Recent message history:",
            _format_messages(recent_messages),
            "",
            f"Now produce the spoken assistant reply first, then {JSON_SENTINEL}, then the JSON object.",
        ]
    )

    return [
        SystemMessage(content=system_content),
        HumanMessage(content=human_content),
    ]