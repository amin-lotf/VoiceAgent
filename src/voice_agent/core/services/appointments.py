from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional, Sequence
from sqlalchemy.exc import IntegrityError

from .exceptions import InvalidSlot, NotFound, SlotNotAvailable
from .utils import ceil_to_grid, iter_daily_slots
from voice_agent.core.db.mappers import to_view
from voice_agent.core.db.uow import SqlAlchemyUnitOfWork
from voice_agent.core.settings import settings
from voice_agent.core.types import AppointmentStatus, AppointmentView, TimeSlot


logger = logging.getLogger(__name__)


def _ensure_tz(dt: datetime) -> None:
    if dt.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")


def _validate_slot_start(slot_start: datetime) -> datetime:
    _ensure_tz(slot_start)
    normalized = slot_start.replace(second=0, microsecond=0)
    aligned = ceil_to_grid(normalized, settings.APPOINTMENT_DURATION_MIN)

    # Require exact alignment (strict grid)
    if aligned != normalized:
        raise InvalidSlot(f"slot_start must align to {settings.APPOINTMENT_DURATION_MIN}-minute grid")

    # Require within opening hours (start must be >= opening, and start < closing)
    open_dt = normalized.replace(hour=settings.OPENING_TIME.hour, minute=settings.OPENING_TIME.minute)
    close_dt = normalized.replace(hour=settings.CLOSING_TIME.hour, minute=settings.CLOSING_TIME.minute)
    if not (open_dt <= normalized < close_dt):
        raise InvalidSlot("slot_start must be within opening hours")

    return normalized


async def list_future_appointments_by_phone(
    uow: SqlAlchemyUnitOfWork,
    *,
    phone: str,
    now: Optional[datetime] = None,
    include_statuses: Sequence[AppointmentStatus] | None = None,
) -> list[AppointmentView]:
    statuses = include_statuses or (AppointmentStatus.HELD, AppointmentStatus.SCHEDULED)
    async with uow:
        rows = await uow.appointments.list_future_by_phone(
            phone=phone,
            now=now,
            include_statuses=statuses,
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
        for slot in iter_daily_slots(cur_day, settings.OPENING_TIME, settings.CLOSING_TIME, settings.APPOINTMENT_DURATION_MIN):
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
    slot_end = slot_start + timedelta(minutes=settings.APPOINTMENT_DURATION_MIN)

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


async def reschedule_appointment(
    uow: SqlAlchemyUnitOfWork,
    *,
    appointment_id: int,
    slot_start: datetime,
) -> AppointmentView:
    slot_start = _validate_slot_start(slot_start)
    slot_end = slot_start + timedelta(minutes=settings.APPOINTMENT_DURATION_MIN)

    try:
        async with uow:
            appt = await uow.appointments.get(appointment_id)
            if appt is None:
                raise NotFound("Appointment not found")
            if appt.status not in (AppointmentStatus.HELD, AppointmentStatus.SCHEDULED):
                raise NotFound("Only active appointments can be rescheduled")
            appt = await uow.appointments.update_fields(
                appointment_id,
                start_at=slot_start,
                end_at=slot_end,
                status=AppointmentStatus.SCHEDULED,
            )
            assert appt is not None
            return to_view(appt)
    except IntegrityError as e:
        raise SlotNotAvailable("That slot is already taken") from e


async def delete_held_appointment(
    uow: SqlAlchemyUnitOfWork,
    *,
    appointment_id: int,
) -> bool:
    """
    Hard-delete a HELD appointment to immediately free the slot.
    Returns True if deleted, False if not found.
    Raises NotFound when appointment exists but is not HELD.
    """
    async with uow:
        appt = await uow.appointments.get(appointment_id)
        if appt is None:
            return False
        if appt.status != AppointmentStatus.HELD:
            raise NotFound("Only HELD appointments can be deleted")
        return await uow.appointments.delete(appointment_id)


async def update_held_appointment_details(
    uow: SqlAlchemyUnitOfWork,
    *,
    appointment_id: int,
    name: str,
    phone: str,
    reason_for_visit: str,
    notes: list[str],
) -> AppointmentView:
    async with uow:
        appt = await uow.appointments.get(appointment_id)
        if appt is None:
            raise NotFound("Appointment not found")
        if appt.status != AppointmentStatus.HELD:
            raise NotFound("Only HELD appointments can be updated here")
        appt = await uow.appointments.update_fields(
            appointment_id,
            name=name,
            phone=phone,
            reason_for_visit=reason_for_visit,
            notes=notes,
        )
        assert appt is not None
        return to_view(appt)


async def update_appointment_notes(
    uow: SqlAlchemyUnitOfWork,
    *,
    appointment_id: int,
    notes: list[str],
) -> AppointmentView:
    async with uow:
        appt = await uow.appointments.get(appointment_id)
        if appt is None:
            raise NotFound("Appointment not found")
        if appt.status not in (AppointmentStatus.HELD, AppointmentStatus.SCHEDULED):
            raise NotFound("Only active appointments can be updated")
        appt = await uow.appointments.update_fields(
            appointment_id,
            notes=notes,
        )
        assert appt is not None
        return to_view(appt)
