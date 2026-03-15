from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from langchain_core.messages import HumanMessage, SystemMessage

from voice_agent.const import DEFAULT_TZ
from voice_agent.core.types import AppointmentDraft


def build_local_basic_info_extract_prompt(
    *,
    user_text: str,
    appointment: AppointmentDraft,
) -> list:
    has_name = bool(appointment.get("name"))
    has_phone = bool(appointment.get("phone"))
    has_reason = bool(appointment.get("reason_for_visit"))

    name_rule = (
        '- name already exists in appointment_draft. '
        'Set patch.name ONLY if caller_text clearly corrects or replaces it. '
        'Valid examples: "actually my name is Jack", "no, my name is Jack", '
        '"that name is wrong, it is Jack". '
        'If caller_text only says a bare name like "Jack", or says a name casually, set patch.name=null.'
        if has_name
        else
        '- Set patch.name only if caller_text explicitly states the caller name, such as '
        '"my name is Jack", "I am Jack", "this is Jack". '
        'A bare name alone is not enough. If unsure, set null.'
    )

    phone_rule = (
        '- phone already exists in appointment_draft. '
        'Set patch.phone ONLY if caller_text clearly corrects or replaces it. '
        'Valid examples: "actually use 0912345678", "no, my number is 0912345678", '
        '"that number is wrong, use 0912345678". '
        'If caller_text only says digits without explicit correction wording, set patch.phone=null.'
        if has_phone
        else
        '- Set patch.phone only if caller_text explicitly gives a phone number. '
        'Output digits only, keep leading + if present. '
        'Convert spoken numbers like "oh" to 0, and "double"/"triple" only when clear. '
        'If unsure, set null.'
    )

    reason_rule = (
        '- reason_for_visit already exists in appointment_draft. '
        'Set patch.reason_for_visit ONLY if caller_text clearly corrects or replaces it. '
        'Valid examples: "actually it is for tooth pain", "not a checkup, it is a follow-up", '
        '"the reason is fever". '
        'Do not replace from weak or ambiguous text.'
        if has_reason
        else
        '- Set patch.reason_for_visit only if caller_text explicitly states a medical visit reason.'
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
    "reason_for_visit": null
  }}
}}

Main rules:
1) patch is DELTA ONLY. Set a field only if caller_text explicitly provides it this turn.
2) If a field already exists in appointment_draft, do NOT replace it unless caller_text clearly corrects it.
3) Corrections must be STRICT. Weak, casual, or ambiguous mentions are NOT corrections.
4) For an existing field, replacement requires explicit correction wording like:
   "actually", "change", "use ... instead", "that is wrong", "not X, Y".
5) If explicit correction wording is missing for an already-filled field, patch for that field MUST be null.
6) reason_for_visit must be medical only. Scheduling language is never a medical reason.

Field rules:
{name_rule}
{phone_rule}
{reason_rule}

Strong correction signals:
"actually", "no", "that is wrong", "use this instead", "change it", "not X, Y".

Without a strong correction signal, do not replace an existing field.

IMPORTANT:
If a field already exists, a bare replacement value is NOT a correction.

Examples:
- existing name=Jack, caller_text="Peter" -> patch.name=null
- existing name=Jack, caller_text="Peter, how about Monday" -> patch.name=null
- existing phone exists, caller_text="0912345678" -> patch.phone=null
- existing reason=checkup, caller_text="fever" -> patch.reason_for_visit=null
- existing reason=checkup, caller_text="actually it is for fever" -> patch.reason_for_visit="fever"

reason_for_visit strict rules:
Valid medical reasons include:
- "checkup"
- "fever"
- "cough"
- "stomach pain"
- "toothache"
- "rash"
- "refill"
- "vaccination"
- "follow-up"
- "consultation"
- "blood test"

Never treat these as reason_for_visit:
- "morning"
- "afternoon"
- "evening"
- "3pm"
- "15:00"
- "tomorrow"
- "next week"
- "earliest"
- "soonest"
- "first available"
- "yes"
- "no"
- weekdays or dates

If the text is not explicit, set the field to null.

""".strip()

    human_payload = {
        "caller_text": user_text,
        "appointment_draft": {
            "name": appointment.get("name"),
            "phone": appointment.get("phone"),
            "reason_for_visit": appointment.get("reason_for_visit"),
        },
    }

    return [
        SystemMessage(content=system_content),
        HumanMessage(content=json.dumps(human_payload, ensure_ascii=False)),
    ]