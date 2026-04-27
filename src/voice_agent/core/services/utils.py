from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta, time
from typing import Iterable

from voice_agent.core.types import TimeSlot


def floor_to_grid(dt: datetime, duration_min: int) -> datetime:
    # assumes tz-aware dt
    minutes = dt.minute + dt.hour * 60
    slot = (minutes // duration_min) * duration_min
    h, m = divmod(slot, 60)
    return dt.replace(hour=h, minute=m, second=0, microsecond=0)

def ceil_to_grid(dt: datetime, duration_min: int) -> datetime:
    floored = floor_to_grid(dt, duration_min)
    if floored == dt.replace(second=0, microsecond=0):
        return floored
    return floored + timedelta(minutes=duration_min)

def iter_daily_slots(day: datetime, opening: time, closing: time, duration_min: int):
    """
    Yields slots within a day using a fixed grid.
    Last-slot rule: we allow a slot whose start is before closing even if end exceeds closing.
    """
    start = day.replace(hour=opening.hour, minute=opening.minute, second=0, microsecond=0)
    end_boundary = day.replace(hour=closing.hour, minute=closing.minute, second=0, microsecond=0)

    cur = start
    step = timedelta(minutes=duration_min)
    while cur < end_boundary:
        yield TimeSlot(start_at=cur, end_at=cur + step)
        cur += step