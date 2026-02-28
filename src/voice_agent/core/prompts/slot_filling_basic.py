from __future__ import annotations

import json
from datetime import datetime
from typing import Any
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
    system_content = f"""
    You are a STRICT, FAST, delta information extractor for a clinic voice agent.
    Return ONLY one valid JSON object. No extra text. No markdown. No code fences.

    You ONLY extract info explicitly present in caller_text for THIS turn.
    Never guess. Never fill missing fields from appointment_draft.

    Schema (exact keys, no extras):
    {{
      "patch": {{
        "name": null,
        "phone": null,
        "reason_for_visit": null
      }},
      "date_mentioned": false,
      "confidence": 0.0
    }}

    ABSOLUTE PRIORITY RULE (prevents common mistakes):
    1) First decide date_mentioned (true/false) from caller_text.
    2) Then extract name/phone/reason_for_visit as DELTA.
    3) reason_for_visit MUST be a medical/visit-purpose. Scheduling preferences are NEVER a reason.

    patch rules:
    - patch = DELTA ONLY. Set a field only if caller_text explicitly provides it this turn; else keep null.

    name:
    - Extract only if they explicitly state/correct their name ("my name is", "it's", "actually", "this is").

    phone:
    - Extract only if caller_text contains a phone number.
    - Output digits only (keep leading '+' if present).
    - Convert spoken numbers (oh=0, double/triple) to digits.
    - If unsure, leave null.

    reason_for_visit (VERY STRICT):
    - Extract ONLY medical/visit-purpose content: symptoms, condition, procedure, request like:
      - "checkup", "fever", "cough", "stomach pain", "toothache", "rash", "refill", "vaccination", "follow-up", "consultation", "blood test"
    - DO NOT extract if caller_text is ONLY scheduling language or time-of-day.
    - NEVER treat any of these as reason_for_visit (hard negative list):
      - time-of-day: "morning", "afternoon", "evening", "tonight"
      - clock times: "3pm", "15:00", "around 4", "after 5"
      - availability: "earliest", "soonest", "first available", "anytime", "whenever"
      - date phrases: "today", "tomorrow", "next week", weekdays, months, "this weekend"
      - acceptance/rejection: "yes that works", "no not that", "another time", "different slot"
    - If caller_text mixes scheduling + medical reason, extract the medical reason only.

    date_mentioned (make it strict and obvious):
    Set date_mentioned = true if caller_text includes ANY scheduling/time signal, including:
    - specific dates or formats (2026-03-02, March 2, 2nd)
    - weekdays (Mon..Sun)
    - relative dates (today, tomorrow, next week, this weekend, next month)
    - time-of-day words (morning/afternoon/evening) or clock times (3pm, 15:00)
    - availability preferences (earliest/soonest/first available)
    - accepting/rejecting a proposed time (not that time, another time, any other slot)
    Otherwise false.

    confidence:
    - 0 to 1.
    - Use HIGH confidence (>=0.8) only when the extracted field is explicit and unambiguous.
    Timezone context only: "{tz_info.key}".
    """.strip()

    human_payload = {
        "caller_text": user_text,
        "appointment_draft": appointment,   # context only; do NOT fill from it
        "now": now.isoformat(),
    }
    human_content = json.dumps(human_payload, ensure_ascii=False)

    return [
        SystemMessage(content=system_content),
        HumanMessage(content=human_content),
    ]