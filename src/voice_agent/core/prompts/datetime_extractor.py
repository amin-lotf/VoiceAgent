from __future__ import annotations

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from langchain_core.messages import HumanMessage, SystemMessage

from voice_agent.const import DEFAULT_TZ, NOT_SPECIFIED
from voice_agent.core.types import AppointmentDraft, CallState


def _pretty_json(data: object) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def build_next_14_days(now: datetime, tz_info: ZoneInfo = DEFAULT_TZ) -> list[dict]:
    local_now = now.astimezone(tz_info)
    today = local_now.date()

    items: list[dict] = []
    for i in range(14):
        d = today + timedelta(days=i)
        weekday = d.strftime("%A")
        month = d.strftime("%B")

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
                "spoken": f"{weekday} {month} {d.day} {d.year}",
                "tags": tags,
            }
        )
    return items


def build_time_resolution_prompt(
    *,
    state: CallState,
    now: datetime,
    tz_info: ZoneInfo = DEFAULT_TZ,
) -> list:
    appointment: AppointmentDraft = dict(state.get("appointment_draft") or {})
    requested_time_text = (appointment.get("requested_time_text") or "").strip()
    last_offered_slot_start_at = (appointment.get("last_offered_slot_start_at") or "").strip()

    next_14_days = build_next_14_days(now=now, tz_info=tz_info)
    prev_user_text=state.get("prev_user_text") or 'none'
    prev_assistant_text=state.get("prev_assistant_text") or 'none'

    output_schema = {
        "schedule_patch": {
            "date_mode": NOT_SPECIFIED,
            "date_key": NOT_SPECIFIED,
            "time_pref": NOT_SPECIFIED,
            "exact_time_text": NOT_SPECIFIED,
            "relative_to_offered": NOT_SPECIFIED,
        }
    }

    system_content = f"""
You are a scheduling-time parser for a medical clinic voice agent.

Your only job:
- Read the caller's raw scheduling phrase from requested_time_text
- Convert it into one compact schedule_patch JSON object

Return exactly one valid JSON object.
No markdown.
No code fences.
No explanation.
No extra text.

Output schema:
{_pretty_json(output_schema)}

Rules:

General:
- requested_time_text is the source text to parse.
- Do NOT produce spoken text.
- Do NOT decide clinic intent, user intent, phase, or any non-time fields.
- Do NOT detect whether datetime exists; assume this node was called because time parsing is needed.
- If the text is too unclear to map safely, keep fields as "{NOT_SPECIFIED}".
- Prefer conservative output over guessing.

Allowed values:

- schedule_patch.date_mode:
  - "{NOT_SPECIFIED}"
  - "specific_day"
  - "earliest"
  - "this_week"
  - "next_week"

- schedule_patch.time_pref:
  - "{NOT_SPECIFIED}"
  - "morning"
  - "afternoon"
  - "exact_time"

- schedule_patch.relative_to_offered:
  - "{NOT_SPECIFIED}"
  - "same_time"
  - "earlier"
  - "later"
  - "next_day"
  - "previous_day"

Field meanings:

- date_mode:
  - use "specific_day" only when the day maps clearly to one exact date_key from the provided next_14_days
  - use "earliest" for phrases like:
    - "earliest"
    - "first available"
    - "soonest"
  - use "this_week" for broad requests like:
    - "this week"
    - "sometime this week"
  - use "next_week" for broad requests like:
    - "next week"
    - "sometime next week"
  - otherwise "{NOT_SPECIFIED}"

- date_key:
  - output one exact date_key from next_14_days only when the requested day maps clearly
  - otherwise "{NOT_SPECIFIED}"

- time_pref:
  - use "morning" for phrases like:
    - "morning"
    - "tomorrow morning"
  - use "afternoon" for phrases like:
    - "afternoon"
    - "tomorrow afternoon"
  - use "exact_time" only when the caller gives a specific clock time
  - otherwise "{NOT_SPECIFIED}"

- exact_time_text:
  - output only normalized 24-hour HH:MM if a specific time is clearly given
  - examples:
    - "10 am" -> "10:00"
    - "10:30 am" -> "10:30"
    - "2 pm" -> "14:00"
    - "2:30 pm" -> "14:30"
    - "14:00" -> "14:00"
  - if no exact time is clearly given, output "{NOT_SPECIFIED}"

Relative-to-offered behavior:
- You are given last_offered_slot_start_at as the latest offered backend slot.
- Use it only when requested_time_text is clearly expressed relative to that offer.
- Examples:
  - "same time" -> relative_to_offered="same_time"
  - "a bit earlier" -> relative_to_offered="earlier"
  - "later" -> relative_to_offered="later"
  - "the next day" / "tomorrow instead" relative to offered slot -> relative_to_offered="next_day"
  - "the day before" -> relative_to_offered="previous_day"

Important:
- If requested_time_text already specifies an absolute day/time, prefer absolute extraction into date_key/time_pref/exact_time_text.
- Only use relative_to_offered when the wording is truly relative.

Day mapping rules:
- Use only these available date anchors:
{_pretty_json(next_14_days)}

- "today" and "tomorrow" must map only from the provided anchors.
- Weekday names like "Tuesday" should map to the matching date_key in the next_14_days list only.
- If a weekday could be ambiguous but only one matching day exists in the provided range, use it.
- If it does not map safely into the 14-day window, keep date_key as "{NOT_SPECIFIED}".

Range handling:
- For simple ranges like:
  - "Tuesday to Friday"
  - "between Tuesday and Friday"
  - "from Monday through Thursday"
  interpret the request as starting from the FIRST mentioned day.
- In those cases:
  - use date_mode="specific_day"
  - set date_key to the first clearly mappable day
  - set time_pref/exact_time_text if present
- If the range is complex or not safely mappable, leave unresolved fields as "{NOT_SPECIFIED}".

Conflict handling:
- If the user says both a broad preference and an exact time, exact time wins for time_pref.
  Example:
  - "tomorrow morning around 10" -> time_pref="exact_time", exact_time_text="10:00"

Examples:

Input: "tomorrow morning"
Output:
{{
  "schedule_patch": {{
    "date_mode": "specific_day",
    "date_key": "<tomorrow date_key>",
    "time_pref": "morning",
    "exact_time_text": "{NOT_SPECIFIED}",
    "relative_to_offered": "{NOT_SPECIFIED}"
  }}
}}

Input: "next Tuesday at 2 pm"
Output:
{{
  "schedule_patch": {{
    "date_mode": "specific_day",
    "date_key": "<matching Tuesday date_key>",
    "time_pref": "exact_time",
    "exact_time_text": "14:00",
    "relative_to_offered": "{NOT_SPECIFIED}"
  }}
}}

Input: "earliest available"
Output:
{{
  "schedule_patch": {{
    "date_mode": "earliest",
    "date_key": "{NOT_SPECIFIED}",
    "time_pref": "{NOT_SPECIFIED}",
    "exact_time_text": "{NOT_SPECIFIED}",
    "relative_to_offered": "{NOT_SPECIFIED}"
  }}
}}

Input: "same time the next day"
Output:
{{
  "schedule_patch": {{
    "date_mode": "{NOT_SPECIFIED}",
    "date_key": "{NOT_SPECIFIED}",
    "time_pref": "{NOT_SPECIFIED}",
    "exact_time_text": "{NOT_SPECIFIED}",
    "relative_to_offered": "next_day"
  }}
}}
""".strip()

    human_content = "\n".join(
        [
            f"Current clinic local time: {now.astimezone(tz_info).isoformat()}",
            "",
            f'Assistant text already produced this turn: "{prev_assistant_text}"\n'
            f"requested_time_text: {requested_time_text or 'none'}",
            f"last_offered_slot_start_at: {last_offered_slot_start_at or 'none'}",
            "",
            "Return the JSON object only.",
        ]
    )

    return [
        SystemMessage(content=system_content),
        HumanMessage(content=human_content),
    ]