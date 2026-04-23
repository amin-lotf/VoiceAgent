


def _enum_values(enum_cls) -> str:
    return ", ".join(e.value for e in enum_cls)

def extend_prompt_section(rules: list[str], title: str, items: list[str]) -> None:
    if not items:
        return
    rules.append(f"[{title}]")
    rules.extend(items)


from datetime import datetime
from zoneinfo import ZoneInfo

DEFAULT_TZ = "Asia/Taipei"


def format_offered_time_for_voice(iso_str: str|None, tz: str = DEFAULT_TZ) -> str:
    """
    Convert ISO datetime string into natural spoken format for voice agents (Retell-friendly).

    Example:
        2026-04-22T09:00:00+08:00 -> "Wednesday, April 22 at 9 AM"
    """
    if not iso_str:
        return ""

    try:
        dt = datetime.fromisoformat(iso_str)
    except ValueError:
        return iso_str  # fallback

    # Convert timezone if needed
    if dt.tzinfo:
        dt = dt.astimezone(ZoneInfo(tz))
    else:
        dt = dt.replace(tzinfo=ZoneInfo(tz))

    # Format parts
    weekday = dt.strftime("%A")
    month = dt.strftime("%B")
    day = dt.day

    hour = dt.hour
    minute = dt.minute

    # 12-hour format
    am_pm = "AM" if hour < 12 else "PM"
    hour_12 = hour % 12 or 12

    if minute == 0:
        time_part = f"{hour_12} {am_pm}"
    else:
        time_part = f"{hour_12}:{minute:02d} {am_pm}"

    return f"{weekday}, {month} {day} at {time_part}"


from typing import List

def format_notes_for_prompt(notes: List[str] | None) -> str:
    if not notes:
        return ""

    cleaned_notes = [
        n.strip().rstrip(".")
        for n in notes
        if n and n.strip()
    ]

    if not cleaned_notes:
        return ""

    # Single note → simpler phrasing
    if len(cleaned_notes) == 1:
        return f"{cleaned_notes[0]} is noted."

    # Multiple notes → slightly more natural flow
    formatted = " ".join(f"{note} is noted." for note in cleaned_notes)
    return formatted