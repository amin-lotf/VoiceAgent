from __future__ import annotations

import re
from typing import Tuple

from voice_agent.core.types import AppointmentSlots, CallEvent, CallState


YES_KEYWORDS = {
    "yes",
    "yeah",
    "yep",
    "yup",
    "sure",
    "correct",
    "right",
    "affirmative",
    "of course",
    "please do",
    "sounds good",
    "that works",
    "ok",
    "okay",
}

NO_KEYWORDS = {
    "no",
    "nope",
    "nah",
    "negative",
    "don't",
    "do not",
    "not really",
    "not now",
    "no thank you",
    "no thanks",
    "stop",
    "cancel",
}

EMERGENCY_KEYWORDS = {
    "chest pain",
    "difficulty breathing",
    "can't breathe",
    "cannot breathe",
    "shortness of breath",
    "severe bleeding",
    "unconscious",
    "fainted",
    "fainting",
    "stroke",
    "heart attack",
    "suicidal",
    "overdose",
}

WEEKDAYS = [
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
]


def ensure_appointment(state: CallState) -> AppointmentSlots:
    """Return an appointment dict on state, creating one if needed."""
    appointment = state.get("appointment")
    if appointment is None:
        appointment = {}
        state["appointment"] = appointment
    return appointment


def ensure_spoken_on_user_turn(state: CallState) -> CallState:
    """
    Guarantee that a USER_TURN ends with a spoken response unless the call is ending.
    """
    if state.get("event") == CallEvent.USER_TURN and not state.get("end_call", False):
        if not (state.get("assistant_text") or "").strip():
            state["assistant_text"] = "Sorry, I didn't catch that. Could you say that again?"
    return state


def is_yes(text: str | None) -> bool:
    if not text:
        return False
    normalized = text.strip().lower()
    return any(normalized == kw or kw in normalized for kw in YES_KEYWORDS)


def is_no(text: str | None) -> bool:
    if not text:
        return False
    normalized = text.strip().lower()
    return any(normalized == kw or kw in normalized for kw in NO_KEYWORDS)


def normalize_phone(text: str | None) -> str | None:
    if not text:
        return None
    digits = "".join(re.findall(r"\\d", text))
    if len(digits) < 10 or len(digits) > 15:
        return None
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits


def is_valid_email(text: str | None) -> bool:
    if not text:
        return False
    return bool(re.match(r"^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$", text.strip()))


def detect_emergency(text: str | None) -> bool:
    if not text:
        return False
    lowered = text.lower()
    return any(keyword in lowered for keyword in EMERGENCY_KEYWORDS)


def parse_date_time(text: str | None) -> Tuple[str | None, str | None, bool]:
    """
    Very lightweight parser for voice input.

    Returns (date_text, time_text, ambiguous).
    """
    if not text:
        return None, None, True

    lowered = text.lower()
    date_text: str | None = None
    time_text: str | None = None
    ambiguous = False

    if "today" in lowered:
        date_text = "today"
    elif "tomorrow" in lowered:
        date_text = "tomorrow"
    else:
        for weekday in WEEKDAYS:
            if weekday in lowered:
                date_text = weekday
                break

    time_match = re.search(r"\\b(\\d{1,2})(?::(\\d{2}))?\\s*(am|pm)?\\b", lowered)
    if time_match:
        hour = int(time_match.group(1))
        minute = time_match.group(2) or "00"
        ampm = time_match.group(3)
        if ampm:
            time_text = f"{hour}:{minute} {ampm}"
        else:
            time_text = f"{hour}:{minute}"
            ambiguous = hour <= 12
    elif "noon" in lowered:
        time_text = "12:00 pm"
    elif "morning" in lowered or "afternoon" in lowered or "evening" in lowered:
        # Keep broad descriptors but mark ambiguous
        if "morning" in lowered:
            time_text = "morning"
        elif "afternoon" in lowered:
            time_text = "afternoon"
        else:
            time_text = "evening"
        ambiguous = True

    if date_text is None:
        ambiguous = True

    return date_text, time_text, ambiguous


def next_missing_slot(appointment: AppointmentSlots) -> str | None:
    if not appointment.get("date_requested") or not appointment.get("time_requested"):
        return "ask_datetime"
    if not appointment.get("name"):
        return "ask_name"
    if not appointment.get("phone"):
        return "ask_phone"
    return None
