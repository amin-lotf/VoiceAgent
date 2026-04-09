import asyncio
from dataclasses import dataclass
from typing import  Callable, Awaitable, TypeVar, Any
from datetime import datetime
from zoneinfo import ZoneInfo
from voice_agent.const import DEFAULT_TZ
T = TypeVar("T")


@dataclass
class RunControl:
    """
    Runtime-only control object injected into state for the currently executing run.
    Must never be persisted.
    """
    set_interruptible: Callable[[bool], None]


async def run_non_interruptible(
    state: dict[str, Any],
    fn: Callable[[], Awaitable[T]],
) -> T:
    """
    Helper for critical sections inside LangGraph nodes.

    Usage:
        async def _commit():
            await confirm_appointment(...)

        await run_non_interruptible(state, _commit)

    This does two things:
    - marks the active run as non-interruptible from the engine's point of view
    - shields the actual critical awaitable from task cancellation
    """
    control = state.get("_run_control")
    if control is not None:
        control.set_interruptible(False)

    try:
        return await asyncio.shield(fn())
    finally:
        if control is not None:
            control.set_interruptible(True)






def iso_to_human_readable(
    iso_str: str,
    *,
    tz: ZoneInfo = DEFAULT_TZ,
    include_weekday: bool = True,
    include_time: bool = True,
) -> str:
    dt = datetime.fromisoformat(iso_str)

    # Normalize timezone (important if DB stores mixed tz)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    else:
        dt = dt.astimezone(tz)

    parts = []

    if include_weekday:
        parts.append(dt.strftime("%A"))  # Monday

    parts.append(dt.strftime("%B %-d"))  # April 13 (Linux/macOS)
    # If on Windows use: "%B %d".lstrip("0")

    if include_time:
        parts.append(dt.strftime("%-I:%M %p"))  # 9:00 AM

    return ", ".join(parts)