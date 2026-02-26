from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, time
from typing import Any
from zoneinfo import ZoneInfo

from langchain_core.messages import HumanMessage, SystemMessage

from voice_agent.const import DEFAULT_TZ
from voice_agent.core.types import AppointmentDraft

logger = logging.getLogger(__name__)

def build_next_days_calendar(now: datetime, days: int = 30,tz_info:ZoneInfo=DEFAULT_TZ) -> list[dict]:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    local_now = now.astimezone(tz_info)

    out: list[dict] = []
    for i in range(days):
        d = (local_now.date() + timedelta(days=i))
        dt0 = datetime.combine(d, time(0, 0), tzinfo=tz_info)
        out.append({
            "date_iso": d.isoformat(),                 # "2026-02-21"
            "weekday": dt0.strftime("%A"),            # "Saturday"
            "label": dt0.strftime("%a, %b %d, %Y"),   # "Sat, Feb 21, 2026"
        })
    return out




def build_slot_fill_prompt(
    *,
    user_text: str,
    appointment: AppointmentDraft,
    now: datetime,
    last_offered: str | None,
    opening_time: str,  # e.g. "09:00"
    closing_time: str,  # e.g. "18:00"
    tz_info:ZoneInfo=DEFAULT_TZ
):
    system_content = f"""
    You are a STRICT delta information extraction model for a medical clinic voice agent.

    You DO NOT manage conversation flow.
    You DO NOT continue the workflow.
    You DO NOT assume the next logical step.
    You ONLY extract new information explicitly stated in caller_text for THIS turn.

    Return ONLY a single valid JSON object.
    No markdown.
    No code fences.
    No explanation.
    No extra keys.

    Output MUST match EXACTLY this schema:

    {{
      "patch": {{
        "notes_append": [],
        "schedule_intent": "unspecified",
        "tz": "{tz_info.key}",
        "desired_start_at": null,
        "range_start_at": null,
        "range_end_at": null,
        "search_days": null
      }},
      "confidence": 0.0
    }}

    ────────────────────────
    CORE RULE: PATCH = DELTA ONLY
    ────────────────────────

    - Only set a field if caller_text explicitly provides that information in THIS turn.
    - Never fill missing fields just because they are missing in appointment_draft.
    - Never infer what the caller “probably means”.
    - Never continue the scheduling process automatically.
    - If information is not explicitly stated in caller_text, leave it null.
    - notes_append defaults to [] if nothing new.

    appointment_draft is context only.
    It is NOT an instruction to complete missing data.

    ────────────────────────
    FIELD RULES
    ────────────────────────

    tz:
    - MUST always be exactly "{tz_info.key}"

    ────────────────────────
    SCHEDULING HARD GATE
    ────────────────────────

    CRITICAL:

    If caller_text does NOT contain scheduling language,
    then you MUST output:

    - "schedule_intent": "unspecified"
    - desired_start_at = null
    - range_start_at = null
    - range_end_at = null
    - search_days = null

    Scheduling language includes:
    - Specific dates (Feb 20, 20th, 2026-02-20)
    - Weekdays (Monday, Sunday)
    - Relative dates (tomorrow, next week, next next week)
    - Ranges (between Monday and Wednesday)
    - "earliest", "soonest", "first available"
    - Rejection of last slot ("no not that time", "another time")

    If NONE of the above appear in caller_text,
    DO NOT touch scheduling fields.

    DO NOT invent a date.
    DO NOT guess the next logical step.
    DO NOT move the conversation forward.

    ────────────────────────
    SCHEDULING INTENT MAPPING
    ────────────────────────

    "specific":
    - User gives one specific date or weekday.
    - Set desired_start_at to that date at opening_time.
    - Leave range_* null.

    "range":
    - User gives window (next week, between X and Y).
    - Set range_start_at at opening_time.
    - Set range_end_at at closing_time.

    "earliest":
    - User explicitly says earliest/soonest/first available.
    - Set range_start_at = now.
    - Set search_days (default 7 unless specified).
    - Set range_end_at = now + search_days.

    "reject_and_search":
    - User rejects last offered slot AND wants alternatives.
    - Extract same as earliest or range.
    - schedule_intent must be reject_and_search.

    "unspecified":
    - No scheduling info.

    ────────────────────────
    DATE RULES
    ────────────────────────

    - Interpret all relative dates using provided "now" and timezone.
    - Never choose a date before now.
    - When constructing date-only requests:
      - Use opening_time for desired_start_at.
      - Range start uses opening_time.
      - Range end uses closing_time.
    - All datetimes MUST be ISO 8601 with timezone offset.

    Week rules:
    - Week starts Monday.
    - "next week" = next calendar week (Mon–Sun) after current week.
    - "next next week" = week after next.

    Weekday-only:
    - If no active week window:
      choose next upcoming occurrence after now.
    - If user says "next Monday":
      choose Monday in next calendar week.

    

    ────────────────────────
    NEGATIVE EXAMPLES
    ────────────────────────

    User: "Checkup"
    → reason_for_visit="checkup"
    → schedule_intent="unspecified"
    → all scheduling fields null

    User: "My name is Amin"
    → name="Amin"
    → schedule_intent="unspecified"

    User: "09xxxxxxx"
    → phone extracted
    → schedule_intent="unspecified"

    These examples are CRITICAL.
    Never invent scheduling.

    ────────────────────────
    MULTI-FIELD TURN EXAMPLE
    ────────────────────────

    User: "Hi I'm Amin, next Tuesday works"
    → name="Amin"
    → schedule_intent="specific"
    → desired_start_at set correctly

    ────────────────────────

    confidence:
    - Float between 0 and 1.
    - Lower confidence if interpretation uncertain.
    """

    human_payload = {
        "caller_text": user_text,
        "appointment_draft": appointment,
        "now": now.isoformat(),
        "calendar_next_30_days": build_next_days_calendar(now, 30),
        "now_weekday": now.strftime("%A"),
        "timezone": tz_info.key,
        "last_offered_slot_start_at": last_offered if last_offered else None,
        "opening_time": opening_time,
        "closing_time": closing_time,
    }
    human_content = json.dumps(human_payload, ensure_ascii=False)

    return [SystemMessage(content=system_content), HumanMessage(content=human_content)]