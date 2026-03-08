from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo

from langchain_core.messages import HumanMessage, SystemMessage

from voice_agent.const import DEFAULT_TZ, DEFAULT_DAYS
from voice_agent.core.types import AppointmentDraft, CallState

logger = logging.getLogger(__name__)

def _state_value(state: CallState, key: str) -> str | None:
    return str(state.get(key) or "none")


def build_next_days_calendar(now: datetime, days: int = DEFAULT_DAYS, tz_info: ZoneInfo = DEFAULT_TZ) -> list[dict]:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    local_now = now.astimezone(tz_info)

    out: list[dict] = []
    for i in range(days):
        d = local_now.date() + timedelta(days=i)
        dt0 = datetime.combine(d, time(0, 0), tzinfo=tz_info)
        out.append(
            {
                "date_iso": d.isoformat(),               # "2026-02-21"
                "weekday": dt0.strftime("%A"),           # "Saturday"
                "label": dt0.strftime("%a, %b %d, %Y"),  # "Sat, Feb 21, 2026"
            }
        )
    return out


def build_slot_fill_prompt(
    *,
    user_text: str,
    state: CallState,
    appointment: AppointmentDraft,
    now: datetime,
    last_offered: str | None,
    opening_time: str,  # e.g. "09:00"
    closing_time: str,  # e.g. "18:00"
    tz_info: ZoneInfo = DEFAULT_TZ,
):
    prev_user_text = _state_value(state, "prev_user_text")
    prev_assistant_text = _state_value(state, "prev_assistant_text")


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
    "search_days": null,

    "time_bucket": null,

    "assistant_text": null,
    "clarify_reason": null
  }},
  "confidence": 0.0
}}

!!!!!!!!!!!!!!!!!!!!!!!!
CORE RULE: PATCH = DELTA ONLY
!!!!!!!!!!!!!!!!!!!!!!!!

- Only set a field if caller_text explicitly provides that information in THIS turn,
  OR it is strictly necessary to interpret explicit scheduling language (per rules below).
- Never fill missing fields just because they are missing in appointment_draft.
- Never infer what the caller "probably means".
- Never continue the scheduling process automatically.
- If information is not explicitly stated in caller_text, leave it null.
- notes_append defaults to [] if nothing new.

appointment_draft is context only.
It is NOT an instruction to complete missing data.

!!!!!!!!!!!!!!!!!!!!!!!!
FIELD RULES
!!!!!!!!!!!!!!!!!!!!!!!!

tz:
- MUST always be exactly "{tz_info.key}"

time_bucket:
- null OR one of: "morning" | "afternoon" | "evening"
- Set ONLY if caller_text implies a bucket AND does NOT provide an exact clock time.
- If caller_text gives an exact clock time ("11am", "3:30pm", "15:00"):
  - time_bucket MUST be null
  - desired_start_at MUST include that exact time

assistant_text / clarify_reason:
- Only set when caller_text creates scheduling ambiguity or requests something impossible (out of booking window).
- Otherwise leave them null.

clarify_reason allowed values (or null):
- "time_ambiguous"
- "date_out_of_range"

!!!!!!!!!!!!!!!!!!!!!!!!
SCHEDULING HARD GATE
!!!!!!!!!!!!!!!!!!!!!!!!

CRITICAL:
If caller_text does NOT contain scheduling language,
then you MUST output:
- schedule_intent="unspecified"
- desired_start_at=null
- search_days=null
- time_bucket=null
- assistant_text=null
- clarify_reason=null

Scheduling language includes:
- Specific dates (Feb 20, 20th, 2026-02-20)
- Weekdays (Monday, Sunday)
- Relative dates (tomorrow, next week, next next week)
- Time-of-day buckets (morning, afternoon, evening, tonight, "this afternoon")
- Specific times (3pm, 15:00)
- "earliest", "soonest", "first available"
- Rejection of last slot ("no not that time", "another time", "something else")

If NONE appear, DO NOT touch scheduling fields.

DO NOT invent a date.
DO NOT guess the next logical step.

!!!!!!!!!!!!!!!!!!!!!!!!
BOOKING WINDOW LIMIT (DEFAULT_DAYS)
!!!!!!!!!!!!!!!!!!!!!!!!

Allowed booking dates are ONLY those present in calendar_next_{DEFAULT_DAYS}_days[*].date_iso.

If caller_text requests a specific date/weekday/relative week that resolves to a date NOT in that list:
- schedule_intent="clarify"
- clarify_reason="date_out_of_range"
- assistant_text="We can only book appointments within the next {DEFAULT_DAYS} days. Do you have a date in that window that works for you?"
- Leave desired_start_at/search_days/time_bucket null.

(Do NOT output dates outside the provided calendar list.)

!!!!!!!!!!!!!!!!!!!!!!!!
SIMPLIFIED SEARCH WINDOW DESIGN (NO RANGES)
!!!!!!!!!!!!!!!!!!!!!!!!

IMPORTANT:
- You do NOT output range_start_at/range_end_at.
- For broad requests like "next week", you output a SINGLE anchor date:
  - desired_start_at = start of the requested period at opening_time
  - time_bucket may be set if stated
  - Python will expand the search window deterministically.

So:
- "next week" => desired_start_at = next calendar week's Monday at opening_time
- "next next week" => desired_start_at = Monday of the week after next at opening_time
- "this week" => desired_start_at = today's date at opening_time (or next valid date after now if you must)
(Still never before now.)

Week starts Monday.

!!!!!!!!!!!!!!!!!!!!!!!!
TIME-OF-DAY ANCHORING (CRITICAL)
!!!!!!!!!!!!!!!!!!!!!!!!

DEICTIC time-of-day (anchored to NOW date):
- "this afternoon", "today afternoon", "this morning", "later today", "tonight"
=> anchor_date = local date of "now" (in tz)

NON-DEICTIC time-of-day (anchored to ACTIVE CONTEXT):
- "afternoon", "in the afternoon", "morning", "evening" (WITHOUT "this/today/tonight")
=> Anchor priority:
   1) If caller_text provides a date/weekday/relative date in THIS turn: anchor to that resolved date.
   2) Else if last_offered_slot_start_at is not null: anchor to DATE of last_offered_slot_start_at.
   3) Else if appointment_draft contains desired_start_at from prior turns: anchor to that DATE.
   4) Else: cannot determine day -> schedule_intent="clarify" with time_ambiguous.

This distinguishes:
- "how about afternoon" (uses active context, usually last offered day)
- "how about this afternoon" (anchored to today)

!!!!!!!!!!!!!!!!!!!!!!!!
TIME BUCKET TO CLOCK TIME
!!!!!!!!!!!!!!!!!!!!!!!!

If time_bucket is set and no exact time is provided:
- morning => desired_start_at time = opening_time
- afternoon => desired_start_at time = max(13:00, opening_time)
- evening/tonight => desired_start_at time = max(17:00, opening_time)

All desired_start_at MUST be full ISO datetimes with timezone offset.

!!!!!!!!!!!!!!!!!!!!!!!!
SCHEDULING INTENT MAPPING
!!!!!!!!!!!!!!!!!!!!!!!!

Valid schedule_intent values:
- "unspecified"
- "specific"
- "earliest"
- "reject_and_search"
- "clarify"

"specific":
- User gives one specific date/weekday/relative day/relative week anchor, optionally with time/bucket.
- Resolve the date first.
- If caller_text provides an exact clock time:
  - Set desired_start_at to that resolved date at the exact time.
  - time_bucket MUST be null.
- Else if caller_text provides a time_bucket:
  - Set desired_start_at using TIME BUCKET TO CLOCK TIME.
- Else:
  - Set desired_start_at to resolved date at opening_time.

"earliest":
- User explicitly says earliest/soonest/first available.
- Set desired_start_at = now (ISO, tz)
- Set search_days (default 7 unless specified).
- time_bucket must be null unless caller_text explicitly says e.g. "earliest afternoon".

"reject_and_search":
- Use when user rejects last offered and asks for alternatives WITHOUT specifying a new concrete target date/week/bucket.
  Examples: "no, anything else?", "another time", "something else".
- If caller_text specifies a new target like "Sunday afternoon", then use "specific" instead.

"clarify":
- Scheduling language exists but you cannot determine a valid anchor.
- In clarify:
  - schedule_intent="clarify"
  - clarify_reason set
  - assistant_text short, professional
  - desired_start_at/search_days/time_bucket must be null

!!!!!!!!!!!!!!!!!!!!!!!!
CLARIFY TRIGGERS & TEMPLATES
!!!!!!!!!!!!!!!!!!!!!!!!

If caller_text includes NON-DEICTIC bucket (e.g. "afternoon") but you cannot anchor it to a day:
- schedule_intent="clarify"
- clarify_reason="time_ambiguous"
- assistant_text="Sure — for which day would you like the afternoon appointment?"
- Leave desired_start_at/search_days/time_bucket null.

!!!!!!!!!!!!!!!!!!!!!!!!
EXAMPLES (CRITICAL)
!!!!!!!!!!!!!!!!!!!!!!!!

User: "Checkup"
- schedule_intent="unspecified"
- all scheduling fields null
- assistant_text null

User: "Sunday"
- schedule_intent="specific"
- desired_start_at = Sunday at opening_time
- time_bucket null

User: "Sunday afternoon"
- schedule_intent="specific"
- desired_start_at = Sunday at opening_time
- time_bucket="afternoon"

User: "How about afternoon?"
Context: last_offered_slot_start_at="2026-03-01T09:00:00+08:00" (Sunday)
- schedule_intent="specific"
- desired_start_at="2026-03-01T{opening_time}+08:00" (ISO)
- time_bucket="afternoon"

User: "How about this afternoon?"
(now is 2026-02-27T10:00:00+08:00)
- schedule_intent="specific"
- desired_start_at="2026-02-27T{opening_time}+08:00"
- time_bucket="afternoon"

User: "Afternoon please"
Context: last_offered is null AND appointment_draft has no desired_start_at
- schedule_intent="clarify"
- clarify_reason="time_ambiguous"
- assistant_text="Sure — for which day would you like the afternoon appointment?"

confidence:
- Float between 0 and 1.
- Lower confidence if interpretation uncertain.
""".strip()

    human_payload = {
        "Previous caller": prev_user_text,
        "Previous assistant": prev_assistant_text,
        "caller_text": (user_text or "").strip(),
        "appointment_draft": appointment,
        "now": now.isoformat(),
        f"calendar_next_{DEFAULT_DAYS}_days": build_next_days_calendar(now, DEFAULT_DAYS, tz_info=tz_info),
        "now_weekday": now.astimezone(tz_info).strftime("%A"),
        "timezone": tz_info.key,
        "last_offered_slot_start_at": last_offered if last_offered else None,
        "opening_time": opening_time,
        "closing_time": closing_time,
    }
    human_content = json.dumps(human_payload, ensure_ascii=False)
    return [SystemMessage(content=system_content), HumanMessage(content=human_content)]