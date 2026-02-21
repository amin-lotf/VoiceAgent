from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, time
from typing import Any
from zoneinfo import ZoneInfo

from langchain_core.messages import HumanMessage, SystemMessage

TZ_NAME = "Asia/Taipei"
TZ = ZoneInfo(TZ_NAME)

logger = logging.getLogger(__name__)

def build_next_days_calendar(now: datetime, days: int = 30) -> list[dict]:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    local_now = now.astimezone(TZ)

    out: list[dict] = []
    for i in range(days):
        d = (local_now.date() + timedelta(days=i))
        dt0 = datetime.combine(d, time(0, 0), tzinfo=TZ)
        out.append({
            "date_iso": d.isoformat(),                 # "2026-02-21"
            "weekday": dt0.strftime("%A"),            # "Saturday"
            "label": dt0.strftime("%a, %b %d, %Y"),   # "Sat, Feb 21, 2026"
        })
    return out

def _serialize(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def build_slot_fill_prompt(
    *,
    user_text: str,
    appointment: dict,
    now: datetime,
    last_offered: datetime | None,
    opening_time: str,  # e.g. "09:00"
    closing_time: str,  # e.g. "18:00"
):
    appt_serialized = {k: _serialize(v) for k, v in (appointment or {}).items()}

    system_content = (
        "You are a strict information extraction model for a medical clinic voice agent.\n"
        "Return ONLY a single valid JSON object (no markdown, no code fences, no prose).\n"
        "Output MUST match this exact shape and keys (no extra keys):\n"
        "{"
        "\"patch\":{"
        "\"name\":null,\"phone\":null,\"reason_for_visit\":null,\"notes_append\":[],"
        "\"schedule_intent\":\"unspecified\",\"tz\":\"Asia/Taipei\","
        "\"desired_start_at\":null,\"range_start_at\":null,\"range_end_at\":null,\"search_days\":null"
        "},"
        "\"confidence\":0.0"
        "}\n"
        "\n"
        "Field rules:\n"
        f"- tz MUST always be exactly \"{TZ_NAME}\".\n"
        "- Never invent name/phone/reason_for_visit. Set them only if explicitly stated.\n"
        "- phone: keep digits and an optional leading '+'. Do not add/remove digits.\n"
        "- desired_start_at/range_start_at/range_end_at must be ISO 8601 with timezone offset "
        "(e.g. 2026-02-20T10:30:00+08:00).\n"
        "- If uncertain, prefer leaving fields null and lower confidence.\n"
        "\n"
        "Clinic hours:\n"
        "- Working hours are provided as opening_time and closing_time.\n"
        "- When you must construct datetimes for a date-only request, anchor times to opening_time.\n"
        "- Any constructed range MUST lie within working hours:\n"
        "  - range_start_at time >= opening_time\n"
        "  - range_end_at time <= closing_time\n"
        "  - range_end_at > range_start_at\n"
        "\n"
        "IMPORTANT: Time-of-day phrases (morning/afternoon/evening) handling:\n"
        "When interpreting relative date phrases (tomorrow, next week, next next, weekday-only), you MUST choose a date that exists in calendar_next_30_days."
        "If not found, leave scheduling fields null and lower confidence."
        "- Do NOT convert time-of-day phrases into specific times.\n"
        "- If the user mentions morning/afternoon/evening, store it ONLY in notes_append as a preference.\n"
        "- The system will book the earliest available slot; your extraction should focus on DATE and SEARCH WINDOW.\n"
        "\n"
        "Scheduling intent mapping (MUST follow):\n"
        "- \"specific\": caller requested a specific datetime with an explicit clock time "
        "(e.g. '3pm', '15:30') OR a specific date only.\n"
        "  - If user provides explicit clock time: set desired_start_at to that exact datetime.\n"
        "  - If user provides only a date (e.g. 'next Monday', 'Feb 20'): set desired_start_at to that date at opening_time.\n"
        "  - Keep range_* null.\n"
        "- \"range\": caller requested a date window (e.g. 'between Monday and Wednesday', 'next week').\n"
        "  - Set range_start_at and range_end_at using opening_time/closing_time boundaries.\n"
        "  - If user gives date-only range: use range_start_at = start_date at opening_time, "
        "range_end_at = end_date at closing_time.\n"
        "- \"earliest\": caller wants the soonest available.\n"
        "  - Set range_start_at=now.\n"
        "  - Set search_days (default 7 unless caller implies otherwise).\n"
        "  - Set range_end_at = now + search_days days.\n"
        "- \"reject_and_search\": caller rejected last offered slot and wants alternatives.\n"
        "  - Same extraction as earliest or range, but schedule_intent must be reject_and_search.\n"
        "- \"unspecified\": no scheduling info.\n"
        "\n"
        "Relative date rules:\n"
        "- Interpret all expressions relative to provided now and timezone.\n"
        "- Convert tomorrow/next week/after Friday into absolute dates (and datetimes using clinic hours).\n"
        "- Never choose a date before now.\n"
        "\n"
        "Week definitions:\n"
        "- A week starts on Monday.\n"
        "- \"next week\" means the next calendar week (Monday 00:00 to Sunday 23:59) after the current week.\n"
        "- \"next next\" / \"week after next\" means the calendar week AFTER next week.\n"
        "  Example: if today is Friday, \"next next\" refers to the Monday of the week after next.\n"
        "\n"
        "Weekday-only rules:\n"
        "- If the user says only a weekday (e.g., 'Sunday'):\n"
        "  - If there is an active requested week window (e.g., next week, next next week), choose that weekday within that window.\n"
        "  - Otherwise choose the next upcoming occurrence of that weekday after now.\n"
        "- If user says \"next <weekday>\", pick that weekday in the next calendar week (NOT merely the next occurrence).\n"
        "- If user says \"next next <weekday>\", pick that weekday in the week after next.\n"
        "\n"
        "notes_append:\n"
        "- Put extra details (preferences/constraints/symptoms/context) as short strings.\n"
        "- Include any time-of-day preference here (e.g. 'prefers afternoon'), without converting it to time.\n"
        "\n"
        "Examples:\n"
        "User: \"Tomorrow afternoon, earliest you have\" => schedule_intent=\"earliest\"; "
        "range_start_at=now; range_end_at=now+7d; notes_append include \"prefers afternoon\".\n"
        "User: \"Next next week\" (today Friday) => schedule_intent=\"range\"; "
        "range_start_at = next-next Monday at opening_time; range_end_at = next-next Sunday at closing_time.\n"
        "User: \"Next Monday\" => schedule_intent=\"specific\"; desired_start_at = next Monday at opening_time.\n"
        "\n"
        "confidence: float 0..1 estimating extraction accuracy.\n"
    )

    human_payload = {
        "user_text": user_text,
        "appointment_draft": appt_serialized,
        "now": now.isoformat(),
        "calendar_next_30_days": build_next_days_calendar(now, 30),
        "now_weekday": now.strftime("%A"),
        "timezone": TZ_NAME,
        "last_offered_slot_start_at": last_offered.isoformat() if last_offered else None,
        "opening_time": opening_time,
        "closing_time": closing_time,
    }
    human_content = json.dumps(human_payload, ensure_ascii=False)


    return [SystemMessage(content=system_content), HumanMessage(content=human_content)]