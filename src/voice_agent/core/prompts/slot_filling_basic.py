from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from langchain_core.messages import HumanMessage, SystemMessage

from voice_agent.const import DEFAULT_TZ
from voice_agent.core.types import AppointmentDraft


def build_local_fast_extract_prompt(
    *,
    user_text: str,
    appointment: AppointmentDraft,
    now: datetime,
    tz_info: ZoneInfo = DEFAULT_TZ,
) -> list:
    has_name = bool(appointment.get("name"))
    has_phone = bool(appointment.get("phone"))
    has_reason = bool(appointment.get("reason_for_visit"))
    has_suggested_date = appointment.get("last_offered_slot_start_at") is not None

    name_rule = (
        '- name is already filled in appointment_draft. '
        'Set patch.name ONLY if caller_text clearly corrects or replaces the existing name. '
        'Strong correction examples: "actually my name is Jack", "no, my name is Jack", '
        '"that name is wrong, it is Jack". '
        'If caller_text only says a name casually or ambiguously, leave patch.name null and name_corrected=false.'
        if has_name
        else
        '- Set patch.name only if caller_text explicitly states the caller name, such as '
        '"my name is Jack", "I am Jack", "this is Jack". '
        'If unsure, leave null.'
    )

    phone_rule = (
        '- phone is already filled in appointment_draft. '
        'Set patch.phone ONLY if caller_text clearly corrects or replaces the existing phone number. '
        'Strong correction examples: "actually use 0912345678", "no, my number is ...", '
        '"that number is wrong". '
        'If caller_text mentions numbers ambiguously, leave patch.phone null and phone_corrected=false.'
        if has_phone
        else
        '- Set patch.phone only if caller_text explicitly provides a phone number. '
        'Output digits only, keep leading + if present. '
        'Convert spoken numbers like "oh"=0, "double" and "triple" when clear. '
        'If unsure, leave null.'
    )

    reason_rule = (
        '- reason_for_visit is already filled in appointment_draft. '
        'Set patch.reason_for_visit ONLY if caller_text clearly corrects or changes the medical reason. '
        'Strong correction examples: "actually it is for tooth pain", "not a checkup, it is a follow-up", '
        '"the reason is fever". '
        'Do not replace the reason from weak or ambiguous text.'
        if has_reason
        else
        '- Set patch.reason_for_visit only if caller_text explicitly states a medical visit reason.'
    )

    suggested_date_rule = (
        '- suggested_date_confirmed is a CONTEXT-BASED confirmation flag, not a date extraction field. '
        '- If appointment_draft.last_offered_slot_start_at exists, and name, phone, and reason_for_visit are already filled, '
        'then short confirmation replies can confirm that offered slot. '
        '- In this case, if caller_text is a clear acceptance reply such as "yes", "okay", "ok", "correct", '
        '"sounds good", "that works", "book it", "that is fine", set patch.suggested_date_confirmed=true '
        'EVEN IF caller_text does not repeat the date. '
        '- This is allowed because appointment_draft provides the currently offered slot context. '
        '- If caller_text rejects, changes, questions, or asks for another time/day, leave patch.suggested_date_confirmed null. '
        '- Never set it to false.'
        if has_suggested_date and has_name and has_phone and has_reason
        else
        '- Do not set patch.suggested_date_confirmed unless appointment_draft.last_offered_slot_start_at exists '
        'and name, phone, and reason_for_visit are already filled.'
    )

    system_content = f"""
You are a STRICT, FAST, delta extractor for a clinic voice agent.
Return ONLY one valid JSON object. No extra text. No markdown. No code fences.

Extract ONLY from caller_text in THIS turn.
Never guess.
Never fill from appointment_draft.
appointment_draft is context only.

Schema (exact keys, no extras):
{{
  "patch": {{
    "name": null,
    "phone": null,
    "reason_for_visit": null,
    "suggested_date_confirmed": null
  }},
  "date_mentioned": false,
  "name_corrected": false,
  "phone_corrected": false,
  "reason_corrected": false,
  "confidence": 0.0
}}

Main rules:
1) patch is DELTA ONLY. Set a field only if caller_text explicitly provides it this turn.
2) If a field already exists in appointment_draft, do NOT replace it unless caller_text clearly corrects it.
3) Corrections must be STRICT. Weak, casual, or ambiguous mentions are NOT corrections.
4) reason_for_visit must be medical only. Scheduling language is never a medical reason.
5) date_mentioned must be decided from caller_text only.

Field rules:
{name_rule}
{phone_rule}
{reason_rule}
{suggested_date_rule}

Strong correction signals include:
"actually", "no", "that is wrong", "use this instead", "not X, Y".
Without a strong correction signal, do not replace an existing field.

Correction flags:
- Set name_corrected=true only when caller_text clearly corrects/replaces the existing name using Strong correction signals.
- Set phone_corrected=true only when caller_text clearly corrects/replaces the existing phone using Strong correction signals.
- Set reason_corrected=true only when caller_text clearly corrects/replaces the existing medical reason using Strong correction signals.
- If there is no clear correction, keep the correction flag false.


IMPORTANT:
If a field already exists, a bare replacement value is NOT a correction.



Only mark a change when caller_text clearly requests replacement/correction.

Valid correction examples:
- "actually my name is Jack"
- "no, my name is Jack"
- "that name is wrong"
- "use this number instead"
- "not a checkup, it is for fever"


reason_for_visit strict rules:
- Valid examples: "checkup", "fever", "cough", "stomach pain", "toothache", "rash",
  "refill", "vaccination", "follow-up", "consultation", "blood test".
- Never treat these as reason_for_visit:
  "morning", "afternoon", "evening", "3pm", "15:00", "tomorrow", "next week",
  "earliest", "soonest", "first available", "yes", "no", "another time".

date_mentioned:
Set date_mentioned=true if caller_text includes any scheduling signal:
- dates, weekdays, months
- relative dates like today, tomorrow, next week
- time-of-day or clock time
- availability words like earliest, soonest, first available
- rejecting/changing a proposed slot like "another time", "different day", "not that time"
Otherwise false.

Examples for correction flags:
- caller_text: "Jack" -> name_corrected=false, name=null
- caller_text: "0912345678" -> phone_corrected=false, phone=null
- caller_text: "checkup" -> reason_corrected=false, reason_for_visit=null

Examples for suggested_date_confirmed:

appointment_draft.last_offered_slot_start_at exists
caller_text: "okay"
-> patch.suggested_date_confirmed = true

appointment_draft.last_offered_slot_start_at exists
caller_text: "yes that works"
-> patch.suggested_date_confirmed = true

appointment_draft.last_offered_slot_start_at exists
caller_text: "book it"
-> patch.suggested_date_confirmed = true

appointment_draft.last_offered_slot_start_at exists
caller_text: "another time"
-> patch.suggested_date_confirmed = null
date_mentioned = true

appointment_draft.last_offered_slot_start_at exists
caller_text: "not that time"
-> patch.suggested_date_confirmed = null
date_mentioned = true

confidence:
- 0.0 to 1.0
- Use >= 0.8 only when the extraction is explicit and unambiguous.

Timezone context only: "{tz_info.key}".
""".strip()

    human_payload = {
        "caller_text": user_text,
        "appointment_draft": appointment,
    }

    return [
        SystemMessage(content=system_content),
        HumanMessage(content=json.dumps(human_payload, ensure_ascii=False)),
    ]