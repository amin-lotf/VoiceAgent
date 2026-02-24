from __future__ import annotations

import re
from datetime import datetime
from logging import Logger
from typing import Any
from zoneinfo import ZoneInfo

from langgraph.config import get_stream_writer

from voice_agent.const import DEFAULT_TZ
from voice_agent.core.types import CallEvent, CallState, AppointmentCreate


def parse_date(value: Any,tz_info:ZoneInfo=DEFAULT_TZ,logger:Logger|None=None) -> datetime | None:

    if not value:
        return None

    try:
        if isinstance(value, datetime):
            dt = value
        elif isinstance(value, str):
            dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        else:
            return None

        # Normalize timezone
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=tz_info)

        return dt.astimezone(tz_info)

    except Exception as e:
        if logger is not None:
            logger.warning("Failed to parse datetime: %s (%s)", value, e)
        return None

def format_date(dt: datetime,tz_info:ZoneInfo=DEFAULT_TZ) -> str:
    if not isinstance(dt, datetime):
        return ""
    local_dt = dt.astimezone(tz_info)
    try:
        return local_dt.strftime("%A, %b %-d at %-I:%M %p")
    except Exception:
        # Windows-compatible (no %-d)
        return local_dt.strftime("%A, %b %d at %I:%M %p").lstrip("0").replace(" 0", " ")


def ensure_spoken_on_user_turn(state: CallState) -> CallState:
    """
    Guarantee that a USER_TURN ends with a spoken response unless the call is ending.
    """
    if state.get("event") == CallEvent.USER_TURN:
        if not state.get('assistant_streamed', False):
            text = "Sorry, I didn't catch that. Could you say that again?"
            state["assistant_text"] = text
            writer = get_stream_writer()
            if writer:
                for word in text.split():
                    writer(("assistant_token", word + " "))
                state["assistant_streamed"] = True
            state['end_call'] = False
    return state


def normalize_phone(text: str | None) -> str | None:
    if not text:
        return None
    digits = "".join(re.findall(r"\d", text))
    # Accept local numbers down to 7 digits; cap at 15 for international formats.
    if len(digits) < 7 or len(digits) > 15:
        return None
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits


def is_appointment_complete(d: dict) -> bool:
    required = ("name", "phone", "reason_for_visit", "start_at", "end_at", "notes", "datetime_confirmed")
    if not all(k in d for k in required):
        return False
    if not d["name"] or not d["phone"] or not d["reason_for_visit"]:
        return False
    if d["start_at"] is None or d["end_at"] is None:
        return False
    if d.get("datetime_confirmed") is not True:
        return False
    if not isinstance(d.get("notes"), list):
        return False
    return True


def safe_json_parse(text: str) -> str:
    """
    Strip code fences / surrounding prose and return the best-effort JSON substring.
    """
    t = (text or "").strip()
    if not t:
        return ""
    if t.startswith("```"):
        t = t.strip("`").strip()
        if t.lower().startswith("json"):
            t = t[4:].strip()
    l = t.find("{")
    r = t.rfind("}")
    if l != -1 and r != -1 and r > l:
        t = t[l: r + 1]
    return t.strip()
