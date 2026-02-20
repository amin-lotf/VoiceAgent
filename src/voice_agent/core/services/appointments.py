from __future__ import annotations
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy.exc import IntegrityError

from .exceptions import InvalidSlot, NotFound, SlotNotAvailable
from .utils import ceil_to_grid, iter_daily_slots
from voice_agent.core.db.mappers import to_view
from voice_agent.core.db.uow import SqlAlchemyUnitOfWork
from voice_agent.core.settings import settings
from voice_agent.core.types import AppointmentStatus, AppointmentView, TimeSlot





def _ensure_tz(dt: datetime) -> None:
    if dt.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")


def _validate_slot_start(slot_start: datetime) -> datetime:
    _ensure_tz(slot_start)
    normalized = slot_start.replace(second=0, microsecond=0)
    aligned = ceil_to_grid(normalized, settings.appointment_duration_min)

    # Require exact alignment (strict grid)
    if aligned != normalized:
        raise InvalidSlot(f"slot_start must align to {settings.appointment_duration_min}-minute grid")

    # Require within opening hours (start must be >= opening, and start < closing)
    open_dt = normalized.replace(hour=settings.opening_time.hour, minute=settings.opening_time.minute)
    close_dt = normalized.replace(hour=settings.closing_time.hour, minute=settings.closing_time.minute)
    if not (open_dt <= normalized < close_dt):
        raise InvalidSlot("slot_start must be within opening hours")

    return normalized


async def list_future_appointments_by_phone(
    uow: SqlAlchemyUnitOfWork,
    *,
    phone: str,
    now: Optional[datetime] = None,
) -> list[AppointmentView]:
    async with uow:
        rows = await uow.appointments.list_future_by_phone(
            phone=phone,
            now=now,
            include_statuses=(AppointmentStatus.HELD, AppointmentStatus.SCHEDULED),
            ascending=True,
        )
        return [to_view(r) for r in rows]


async def list_free_slots(
    uow: SqlAlchemyUnitOfWork,
    *,
    start_range: datetime,
    end_range: datetime,
) -> list[TimeSlot]:
    """
    Returns available fixed-grid slots between two datetimes.
    """
    _ensure_tz(start_range)
    _ensure_tz(end_range)
    if end_range <= start_range:
        return []

    # Fetch busy intervals once
    async with uow:
        busy = await uow.appointments.list_busy_between(
            start_range=start_range,
            end_range=end_range,
            active_statuses=(AppointmentStatus.HELD, AppointmentStatus.SCHEDULED),
        )

    # Convert busy appointments to a set of busy slot starts (grid assumption)
    busy_starts = {b.start_at.replace(second=0, microsecond=0) for b in busy}

    # Build all candidate slots across days
    out: list[TimeSlot] = []
    day = start_range.replace(hour=0, minute=0, second=0, microsecond=0)
    end_day = end_range.replace(hour=0, minute=0, second=0, microsecond=0)

    cur_day = day
    while cur_day <= end_day:
        for slot in iter_daily_slots(cur_day, settings.opening_time, settings.closing_time, settings.appointment_duration_min):
            if slot.start_at < start_range or slot.start_at >= end_range:
                continue
            if slot.start_at in busy_starts:
                continue
            out.append(slot)
        cur_day += timedelta(days=1)

    return out


async def hold_slot(
    uow: SqlAlchemyUnitOfWork,
    *,
    slot_start: datetime,
    name: str,
    phone: str,
    reason_for_visit: str,
    notes: list[str],
) -> AppointmentView:
    """
    Creates HELD appointment at a fixed slot. If slot already taken, raises SlotNotAvailable.
    """
    slot_start = _validate_slot_start(slot_start)
    slot_end = slot_start + timedelta(minutes=settings.appointment_duration_min)

    try:
        async with uow:
            appt = await uow.appointments.create(
                name=name,
                phone=phone,
                reason_for_visit=reason_for_visit,
                start_at=slot_start,
                end_at=slot_end,
                notes=notes,
                status=AppointmentStatus.HELD,
            )
            return to_view(appt)
    except IntegrityError as e:
        # Your ExcludeConstraint should raise an IntegrityError on overlap
        raise SlotNotAvailable("That slot is already taken") from e


async def confirm_appointment(
    uow: SqlAlchemyUnitOfWork,
    *,
    appointment_id: int,
) -> AppointmentView:
    async with uow:
        appt = await uow.appointments.get(appointment_id)
        if appt is None:
            raise NotFound("Appointment not found")
        appt = await uow.appointments.set_status(appointment_id, AppointmentStatus.SCHEDULED)
        assert appt is not None
        return to_view(appt)


async def cancel_appointment(
    uow: SqlAlchemyUnitOfWork,
    *,
    appointment_id: int,
) -> AppointmentView:
    async with uow:
        appt = await uow.appointments.get(appointment_id)
        if appt is None:
            raise NotFound("Appointment not found")
        appt = await uow.appointments.set_status(appointment_id, AppointmentStatus.CANCELLED)
        assert appt is not None
        return to_view(appt)