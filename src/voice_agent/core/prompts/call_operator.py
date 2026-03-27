from __future__ import annotations

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from langchain_core.messages import HumanMessage, SystemMessage

from voice_agent.const import DEFAULT_TZ, JSON_SENTINEL, NOT_SPECIFIED
from voice_agent.core.types import AppointmentDraft, CallState, AssistantPhase


# -------------------------------------------------------------------
# Suggested enum update
# -------------------------------------------------------------------
#
# class AssistantPhase(StrEnum):
#     COLLECTING_INFO = "collecting_info"
#     SEARCHING_SLOT = "searching_slot"
#     AWAITING_SLOT_CONFIRMATION = "awaiting_slot_confirmation"
#     FINALIZING_APPOINTMENT = "finalizing_appointment"
#     POST_APPOINTMENT = "post_appointment"
#     DONE = "done"
# -------------------------------------------------------------------


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


def _has_requested_time(appointment: AppointmentDraft) -> bool:
    return bool(appointment.get("requested_time"))


def _all_basic_info_collected(appointment: AppointmentDraft) -> bool:
    return bool(
        appointment.get("phone")
        and appointment.get("name")
        and appointment.get("reason_for_visit")
    )


def _all_required_info_collected(appointment: AppointmentDraft) -> bool:
    return bool(
        appointment.get("phone")
        and appointment.get("name")
        and appointment.get("reason_for_visit")
        and appointment.get("requested_time")
    )


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
    if not appointment.get("requested_time"):
        return "date_time"
    return "none"


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
    has_requested_time = bool(appointment.get("requested_time"))
    basic_done = _all_basic_info_collected(appointment)

    if current_step == "none":
        return """
Collection behavior:
- The caller's scheduling intent is not yet clear, or all required collection fields are already complete.
- Do not force another collection question unless a field is still actually missing.
- You may still extract any clearly volunteered phone, name, reason_for_visit, or scheduling info from this turn.
- Ask at most ONE question.
""".strip()

    rules: list[str] = [
        "Collection behavior:",
        "- Ask at most ONE question.",
        "- You may extract any clearly stated phone, name, reason_for_visit, or date/time info from the caller's utterance, even if you do not ask about it.",
        "- If the caller clearly corrects or replaces an already collected field, update patch with the new value.",
        "- Never ask again for a field that is already filled unless the caller is clearly changing it.",
        "- Questions must always be OPEN - ENDED.",
        "  - Do NOT guide the user's answer with examples or options."
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

    if basic_done and not has_requested_time:
        rules.extend(
            [
                "- Phone, name, and reason_for_visit are already collected.",
                "- Date/time collection is now allowed.",
                '- If you ask a scheduling question, ask only for appointment date/time preference.',
            ]
        )
    elif not basic_done:
        rules.extend(
            [
                "- Do not start date/time collection yet.",
                "- Do not ask about appointment date or time until phone, name, and reason_for_visit are all filled.",
                "- If the caller volunteers date/time anyway, you may detect and extract it in JSON, but do not move the conversation to date/time yet.",
            ]
        )
    else:
        rules.append("- requested_time already exists. Do not ask for another date/time unless the caller is clearly changing it.")

    return "\n".join(rules)


def _build_phase_rules() -> str:
    return f"""
Assistant phase rules:
- You must output exactly one assistant_phase from:
  - {AssistantPhase.COLLECTING_INFO.value}
  - {AssistantPhase.SEARCHING_SLOT.value}
  - {AssistantPhase.AWAITING_SLOT_CONFIRMATION.value}
  - {AssistantPhase.FINALIZING_APPOINTMENT.value}
  - {AssistantPhase.POST_APPOINTMENT.value}
  - {AssistantPhase.DONE.value}

Definitions:
- COLLECTING_INFO:
  - Use when any required field is still missing:
    - phone
    - name
    - reason_for_visit
    - requested_time
  - Use when you are still asking a question to collect or clarify required information.
  - In this phase, if the spoken reply asks a real question, set is_pending_question=true.

- SEARCHING_SLOT:
  - Use when all required fields are available for scheduling:
    - phone
    - name
    - reason_for_visit
    - requested_time
  - And there is no unanswered pending question.
  - And no offered slot is currently available yet.
  - In this phase, do NOT ask another question.
  - The spoken reply should say a short processing line such as:
    - "Got it. One moment while I check availability."
  - Set is_pending_question=false.

- AWAITING_SLOT_CONFIRMATION:
  - Use when all required scheduling fields exist AND last_offered_slot_start_at already exists, but the caller has NOT yet confirmed that offered slot.
  - This is the phase where you present the offered slot and ask the caller to confirm yes/no.
  - In this phase, the spoken reply SHOULD usually be a confirmation question.
  - If requested_time_text exists, use it naturally when presenting the slot.
  - Examples:
    - "You asked for tomorrow morning. I found 10 AM. Does that work for you?"
    - "You requested next Tuesday at 2 PM. That time is not available, but I do have 3 PM. Would you like me to book that?"
    - "I found an available slot at 10 AM tomorrow. Would you like me to confirm it?"
  - Set is_pending_question=true when you ask that confirmation question.

- FINALIZING_APPOINTMENT:
  - Use when the caller has clearly accepted the offered slot and the backend should now confirm/finalize it.
  - In this phase, do NOT ask another question.
  - The spoken reply should be a short non-question line like:
    - "Perfect. Let me finalize that for you."
    - "Great. I'll confirm that now."
  - Set is_pending_question=false.

- POST_APPOINTMENT:
  - Use when the appointment has just been completed/booked and the assistant should ask whether anything else should be noted or added.
  - This is the one allowed post-booking question phase.
  - Example spoken reply:
    - "Your appointment is booked. Is there anything else you'd like me to note?"
  - Set is_pending_question=true.

- DONE:
  - Use when the conversation is finished after post-appointment handling or clear goodbye.
  - Example spoken reply:
    - "You're all set. See you then. Goodbye."
  - Set is_pending_question=false.

Pending-question resolution:
- You will be given:
  - current persisted phase
  - pending_question from prior turn, if any
  - current caller text
- If pending_question exists and the current caller text clearly answers it, treat that pending question as resolved for this turn.
- Do NOT keep the conversation in a question-asking state just because pending_question exists in memory if the current caller text answered it.
- If you ask a new question in this turn, set is_pending_question=true.
- If you do not ask a question in this turn, set is_pending_question=false.

Slot confirmation behavior:
- If last_offered_slot_start_at exists and the caller has not clearly accepted or rejected it yet, use awaiting_slot_confirmation.
- If current persisted phase is awaiting_slot_confirmation and the caller clearly says yes, yes please, okay, that works, confirm it, book it, or similar acceptance, move to FINALIZING_APPOINTMENT.
- If current persisted phase is awaiting_slot_confirmation and the caller clearly rejects the offered slot, remain in COLLECTING_INFO or continue scheduling conversation naturally to get another preference.
- Do not jump directly from SEARCHING_SLOT to FINALIZING_APPOINTMENT unless the caller has already clearly confirmed the offered slot.

How to talk about requested vs offered time:
- requested_time_text stores the caller's original natural scheduling wording.
- requested_time may be normalized or backend-resolved.
- last_offered_slot_start_at is the actual held slot from backend.
- You do NOT need to claim they are identical.
- If the original request was broad, like "tomorrow morning", and the offered slot is specific, like 10 AM, present it as a match within that broad preference.
- If the original request was exact and the offered slot differs, explicitly say the requested time was unavailable and offer the alternative.
- Be natural and concise. Do not mention internal fields.

Phase priority:
1) If the caller is ending the call -> DONE
2) If current persisted phase is POST_APPOINTMENT and the caller has nothing else or says goodbye -> DONE
3) If current persisted phase is FINALIZING_APPOINTMENT and the appointment is now being communicated as booked -> POST_APPOINTMENT
4) If current persisted phase is awaiting_slot_confirmation and the caller clearly accepts the offered slot -> FINALIZING_APPOINTMENT
5) If all required info exists and last_offered_slot_start_at exists and the caller has NOT clearly accepted yet -> awaiting_slot_confirmation
6) If all required info exists and last_offered_slot_start_at does NOT exist and there is no active unanswered question -> SEARCHING_SLOT
7) Otherwise -> COLLECTING_INFO
""".strip()


def build_call_operator_prompt(
    *,
    state: CallState,
    now: datetime,
    tz_info: ZoneInfo = DEFAULT_TZ,
) -> list:
    user_text = (state.get("user_text") or "").strip()
    assistant_text = (state.get("assistant_text") or "").strip()
    pending_question = (state.get("pending_question") or "").strip()
    current_phase = str(state.get("phase") or "").strip() or AssistantPhase.COLLECTING_INFO.value

    appointment: AppointmentDraft = state.get("appointment_draft") or {}
    current_user_intent = str(state.get("user_intent") or "undecided").strip() or "undecided"
    recent_messages = _get_recent_messages(state, limit=10)

    confirmed_name = appointment.get("name")
    confirmed_phone = appointment.get("phone")
    confirmed_reason = appointment.get("reason_for_visit")
    confirmed_requested_time = appointment.get("requested_time")
    confirmed_requested_time_text = appointment.get("requested_time_text")
    last_offered_slot_start_at = appointment.get("last_offered_slot_start_at")

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
    phase_rules = _build_phase_rules()

    basic_done = _all_basic_info_collected(appointment)
    all_required_done = _all_required_info_collected(appointment)

    next_14_days = build_next_14_days(now=now, tz_info=tz_info) if basic_done else None

    output_schema = {
        "user_intent": default_user_intent,
        "clinic_intent": "continue",
        "end_call": False,
        "assistant_phase": AssistantPhase.COLLECTING_INFO.value,
        "is_pending_question": True,
        "current_step": current_step,
        "patch": {
            "name": NOT_SPECIFIED,
            "phone": NOT_SPECIFIED,
            "reason_for_visit": NOT_SPECIFIED,
            "requested_time": NOT_SPECIFIED,
            "notes": [],
        },
        "datetime_detected": False,
        "schedule_patch": {
            "date_mode": NOT_SPECIFIED,
            "date_key": NOT_SPECIFIED,
            "time_pref": NOT_SPECIFIED,
            "exact_time_text": NOT_SPECIFIED,
        },
    }

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
  - otherwise use "{NOT_SPECIFIED}"

- schedule_patch.date_key:
  - output one exact date_key from the provided 14-day list only when the caller clearly selected or mentioned that specific day
  - otherwise output "{NOT_SPECIFIED}"

- schedule_patch.time_pref:
  - allowed values: not_specified, morning, afternoon, exact_time
  - use "morning" for requests like "morning"
  - use "afternoon" for requests like "afternoon"
  - use "exact_time" only when caller gives a specific clock time such as "10", "10 am", "2:30 pm", "14:00"
  - otherwise use "{NOT_SPECIFIED}"

- schedule_patch.exact_time_text:
  - output ONLY a normalized 24-hour time string in HH:MM format when schedule_patch.time_pref="exact_time"
  - examples:
    - "10 am" -> "10:00"
    - "10:30 am" -> "10:30"
    - "2 pm" -> "14:00"
    - "2:30 pm" -> "14:30"
    - "14:00" -> "14:00"
  - if no exact clock time is clearly given, output "{NOT_SPECIFIED}"

- patch.requested_time:
  - output a plain string only if the caller clearly gives or updates scheduling preference in this turn
  - this can be natural language, for example:
    - "tomorrow morning"
    - "next Tuesday at 10:00"
    - "earliest available"
  - otherwise output "{NOT_SPECIFIED}"
  
- patch.notes:
  - Always output a list of short strings.
  - Extract any additional useful information that is NOT one of:
    - name
    - phone
    - reason_for_visit
    - requested_time
  - Examples of notes:
    - "prefers female doctor"
    - "first time visit"
    - "has insurance"
    - "needs wheelchair access"
    - "follow-up appointment"
    - "pain started last week"
  - Do NOT duplicate reason_for_visit inside notes.
  - If nothing relevant → output empty list []

- If the caller gives an out-of-range or vague date, ask them to choose a specific day.
- If the caller gives a simple date range with a clear starting day, interpret the request as starting from the FIRST day of that range.
- For examples like "Tuesday to Friday", "between Tuesday and Friday", or "from Monday through Thursday":
  - set datetime_detected = true
  - set schedule_patch.date_mode = "specific_day"
  - set schedule_patch.date_key to the first mentioned day if it maps clearly to one of the provided date_key values
  - set patch.requested_time to the caller's scheduling wording if helpful
  - do not ask for clarification yet
  - leave time_pref and exact_time_text based on what the caller said
- If the range is complicated, ambiguous, non-contiguous, or cannot be mapped clearly to one start day, ask the caller to be more specific.
""".strip()
    else:
        date_rules = f"""
Date/time rules:
- Date/time collection is NOT allowed yet because phone, name, and reason_for_visit are not all filled.
- Do not ask about date or time in this turn.
- If the caller mentions date/time anyway, set datetime_detected=true.
- patch.requested_time should remain "{NOT_SPECIFIED}" unless you intentionally want to store volunteered date/time text before basics are done.
- Keep schedule_patch.date_mode="{NOT_SPECIFIED}", schedule_patch.date_key="{NOT_SPECIFIED}", schedule_patch.time_pref="{NOT_SPECIFIED}", and schedule_patch.exact_time_text="{NOT_SPECIFIED}" unless your backend intentionally wants volunteered date/time captured early.
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

- assistant_phase:
  - must follow the phase rules below exactly

- is_pending_question:
  - true only when the spoken assistant reply in THIS turn asks a real question that expects a caller answer
  - false for processing lines, finalizing lines, goodbye lines, and non-question lines

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

- patch.requested_time:
  - output the new value only if the caller explicitly gives or clearly confirms/corrects their scheduling preference in this turn
  - otherwise output "{NOT_SPECIFIED}"

- datetime_detected:
  - true if this turn mentions any date/time/scheduling expression
  - otherwise false

{phase_rules}

{collection_rules}

{date_rules}

Speaking behavior:
- Sound natural, calm, and brief.
- If the caller already gave useful info in this turn, acknowledge it briefly before asking the next question.
- Never ask for the same field again if it was clearly provided in this turn.
- If office info is asked together with scheduling info, answer briefly and then continue with the single allowed next question only if you are still in COLLECTING_INFO.
- In SEARCHING_SLOT, do not ask a question.
- In awaiting_slot_confirmation, usually ask one short yes/no confirmation question about the offered slot.
- In FINALIZING_APPOINTMENT, do not ask a question.
- In POST_APPOINTMENT, ask only one short post-booking question.
- In DONE, do not ask a question.
- Never end the response with only an acknowledgment when still in COLLECTING_INFO.
- When the caller gives a simple date range, do not explain internal interpretation.
- Treat it as availability starting from the first day of the range.
- Only ask for clarification if the range is ambiguous or too broad to map safely.
- If the user already gave a vague time (e.g., "tomorrow morning"), do NOT ask to clarify time further.
- Proceed naturally to backend slot search.
STRICT RULES — DO NOT SUGGEST OPTIONS:

- NEVER suggest specific times (e.g., "9 or 10?", "morning or afternoon?", "10 AM works?")
- NEVER give multiple choice options for time.
- NEVER assume a time.

- If the user gives a broad time (e.g., "tomorrow morning"):
  - Accept it naturally.
  - DO NOT ask to refine it into exact hours.
  - Let backend resolve it.

- Only ask:
  - "What time works best for you?"
  - NOT "Is 9 or 10 okay?"

BAD:
- "Would 9 or 10 work?"
- "Morning or afternoon?"

GOOD:
- "What time works best for you?"
- NEVER suggest reasons for visit.
- NEVER give examples like:
  - "Is it a checkup, pain, or something else?"

- Always ask open-ended:
  - "What is the reason for your visit?"

BAD:
- "Is it a consultation or checkup?"
GOOD:
- "What is the reason for your visit?"

""".strip()

    human_content = "\n".join(
        [
            f"Current clinic local time: {now.astimezone(tz_info).isoformat()}",
            f"Caller now: {user_text or '[silence]'}",
            f"Assistant text already produced this turn: {assistant_text or 'none'}",
            "",
            f"Current persisted phase: {current_phase}",
            f"Pending question from prior turn: {pending_question or 'none'}",
            "",
            f"Current state user_intent: {current_user_intent}",
            f"Current required step: {current_step}",
            f"Basic info complete: {basic_done}",
            f"All required scheduling info complete: {all_required_done}",
            "",
            "Current appointment draft:",
            _pretty_json(
                {
                    "name": confirmed_name or "none",
                    "phone": confirmed_phone or "none",
                    "reason_for_visit": confirmed_reason or "none",
                    "requested_time": confirmed_requested_time or "none",
                    "requested_time_text": confirmed_requested_time_text or "none",
                    "last_offered_slot_start_at": last_offered_slot_start_at or "none",
                }
            ),
            "",
            "Recent message history:",
            _format_messages(recent_messages),
            "",
            "Important turn objective:",
            "- If required fields are still missing, continue collecting exactly one thing at a time.",
            "- If all required fields are now complete and no unanswered question remains, stop asking questions and move to SEARCHING_SLOT.",
            "- If a slot has already been found and stored in last_offered_slot_start_at, present that offered slot to the caller and ask for confirmation in awaiting_slot_confirmation unless the caller already clearly accepted it.",
            "- If current phase is awaiting_slot_confirmation and the caller clearly accepts the offered slot, move to FINALIZING_APPOINTMENT with no question.",
            "- If current persisted phase is FINALIZING_APPOINTMENT and the appointment is being communicated as booked, move to POST_APPOINTMENT.",
            "- If current persisted phase is POST_APPOINTMENT and the caller has nothing else, move to DONE.",
            "",
            f"Now produce the spoken assistant reply first, then {JSON_SENTINEL}, then the JSON object.",
        ]
    )

    return [
        SystemMessage(content=system_content),
        HumanMessage(content=human_content),
    ]