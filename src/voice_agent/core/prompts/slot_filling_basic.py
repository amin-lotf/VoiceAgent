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

Rules:
- patch = DELTA ONLY. Set a field only if caller_text explicitly provides it this turn; else keep null.
- name: extract if they state their name or correct it ("my name is", "it's", "actually").
- reason_for_visit: extract if they state why (checkup, pain, refill, consultation, etc.).
- phone:
  - extract only if caller_text provides a phone number.
  - output digits only (keep leading '+' if present).
  - If number is spoken as words (zero/one/two..., oh=o, double/triple), convert to digits.
  - If unsure, leave phone null.
-reason_for_visit:
  - extract only if caller_text provides a reason for visit.
  - If unsure, leave reason_for_visit null.
  - Do not consider appointment as a reason for visit.
date_mentioned:
- true if caller_text includes ANY scheduling/date signal (do not compute dates):
  - specific dates or date formats (2026-03-02, March 2, 2nd)
  - weekdays (Mon..Sun)
  - relative date words (today, tomorrow, next week, this weekend, next month)
  - time requests (morning, afternoon, 3pm, 15:00) OR "earliest/soonest/first available"
  - rejecting a proposed time ("not that time", "another time", "any other slot")
- otherwise false.

confidence:
- 0 to 1. Lower if ambiguous or partial.
Timezone for interpretation context only: "{tz_info.key}".
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