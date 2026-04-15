from __future__ import annotations

import re

_RESCHEDULE_HINTS = (
    "reschedule",
    "change it",
    "change that",
    "change to",
    "move it",
    "move that",
    "move my",
    "switch it",
    "switch that",
    "switch to",
    "different time",
    "different day",
)

_DATETIME_HINTS = (
    "today",
    "tomorrow",
    "tonight",
    "morning",
    "afternoon",
    "evening",
    "weekend",
    "next ",
    "this ",
)

_WEEKDAY_HINTS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)

_MONTH_HINTS = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
    "jan ",
    "feb ",
    "mar ",
    "apr ",
    "jun ",
    "jul ",
    "aug ",
    "sep ",
    "sept ",
    "oct ",
    "nov ",
    "dec ",
)

_ACCEPTANCE_PHRASES = {
    "yes",
    "yes please",
    "yeah",
    "yep",
    "sure",
    "ok",
    "okay",
    "that works",
    "works for me",
    "sounds good",
    "perfect",
}


def normalize_text(text: str) -> str:
    return " ".join((text or "").strip().lower().split())


def looks_like_datetime_reference(text: str) -> bool:
    normalized = normalize_text(text)
    if not normalized:
        return False

    if any(token in normalized for token in _DATETIME_HINTS):
        return True
    if any(token in normalized for token in _WEEKDAY_HINTS):
        return True
    if any(token in normalized for token in _MONTH_HINTS):
        return True
    if re.search(r"\b\d{1,2}(?::\d{2})?\s?(?:a\.?m\.?|p\.?m\.?)\b", normalized):
        return True
    return bool(re.search(r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b", normalized))


def looks_like_schedule_change(text: str) -> bool:
    normalized = normalize_text(text)
    if not normalized:
        return False

    if any(token in normalized for token in _RESCHEDULE_HINTS):
        return True
    return looks_like_datetime_reference(normalized)


def looks_like_acceptance(text: str) -> bool:
    normalized = normalize_text(text)
    if not normalized:
        return False
    if normalized in _ACCEPTANCE_PHRASES:
        return True
    return any(
        phrase in normalized
        for phrase in ("that works", "works for me", "sounds good", "yes that works")
    )
