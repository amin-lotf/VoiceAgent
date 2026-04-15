from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Sequence
from sqlalchemy.exc import IntegrityError

from voice_agent.const import DEFAULT_DAYS
from .exceptions import InvalidSlot, NotFound, SlotNotAvailable
from .utils import ceil_to_grid, iter_daily_slots
from voice_agent.core.db.mappers import to_view
from voice_agent.core.db.uow import SqlAlchemyUnitOfWork
from voice_agent.core.settings import settings
from voice_agent.core.types import AppointmentStatus, AppointmentView, TimeSlot

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class HoldAppointmentResult:
    held_view: AppointmentView
    scheduled_view: AppointmentView | None


@dataclass(frozen=True, slots=True)
class ScheduleAppointmentResult:
    scheduled_view: AppointmentView
    deleted_scheduled_view: AppointmentView | None


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


def _normalize_requested_start(slot_start: datetime) -> datetime:
    _ensure_tz(slot_start)
    return slot_start.replace(second=0, microsecond=0)


def _normalize_notes(notes: list[str] | None) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for item in notes or []:
        text = str(item).strip()
        if not text or text in seen:
            continue
        normalized.append(text)
        seen.add(text)
    return normalized


def _notes_from_appointment(appointment: object | None) -> list[str]:
    if appointment is None:
        return []
    return _normalize_notes(getattr(appointment, "notes", None))


async def _find_first_available_slot(
    uow: SqlAlchemyUnitOfWork,
    *,
    requested_start: datetime,
    exclude_appointment_id: int | None = None,
    search_days: int = DEFAULT_DAYS,
) -> TimeSlot:
    normalized_requested = _normalize_requested_start(requested_start)
    now = datetime.now(tz=normalized_requested.tzinfo).replace(second=0, microsecond=0)
    search_start = max(normalized_requested, now)
    search_end = search_start + timedelta(days=search_days)

    busy = await uow.appointments.list_busy_between(
        start_range=search_start,
        end_range=search_end,
        active_statuses=(AppointmentStatus.HELD, AppointmentStatus.SCHEDULED),
        exclude_appointment_id=exclude_appointment_id,
    )

    cur_day = search_start.replace(hour=0, minute=0, second=0, microsecond=0)
    end_day = search_end.replace(hour=0, minute=0, second=0, microsecond=0)

    while cur_day <= end_day:
        for slot in iter_daily_slots(
            cur_day,
            settings.OPENING_TIME,
            settings.CLOSING_TIME,
            settings.APPOINTMENT_DURATION_MIN,
        ):
            if slot.start_at < search_start or slot.start_at >= search_end:
                continue

            is_blocked = any(
                b.start_at is not None
                and b.end_at is not None
                and b.start_at < slot.end_at
                and b.end_at > slot.start_at
                for b in busy
            )
            if is_blocked:
                continue

            return slot
        cur_day += timedelta(days=1)

    raise SlotNotAvailable("No free appointment slots were found")


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
        exclude_appointment_id: int | None = None,
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
            exclude_appointment_id=exclude_appointment_id,
        )

    # Convert busy appointments to a set of busy slot starts (grid assumption)
    busy_starts = {b.start_at.replace(second=0, microsecond=0) for b in busy}

    # Build all candidate slots across days
    out: list[TimeSlot] = []
    day = start_range.replace(hour=0, minute=0, second=0, microsecond=0)
    end_day = end_range.replace(hour=0, minute=0, second=0, microsecond=0)

    cur_day = day
    while cur_day <= end_day:
        for slot in iter_daily_slots(cur_day, settings.OPENING_TIME, settings.CLOSING_TIME,
                                     settings.APPOINTMENT_DURATION_MIN):
            if slot.start_at < start_range or slot.start_at >= end_range:
                continue
            if slot.start_at in busy_starts:
                continue
            out.append(slot)
        cur_day += timedelta(days=1)

    return out


async def create_appointment(
        uow: SqlAlchemyUnitOfWork,
        *,
        name: str,
        phone: str,
        reason_for_visit: str,
        notes: list[str],
) -> AppointmentView:
    """
    Creates a PENDING appointment shell before a slot is chosen.
    """

    try:
        async with uow:
            appt = await uow.appointments.create(
                name=name,
                phone=phone,
                reason_for_visit=reason_for_visit,
                notes=notes,
                status=AppointmentStatus.PENDING,
            )
            return to_view(appt)
    except Exception as e:
        raise InvalidSlot("Failed to create appointment") from e


async def hold_appointment(
        uow: SqlAlchemyUnitOfWork,
        *,
        appointment_id: int,
        slot_start: datetime,
) -> AppointmentView:
    slot_start = _validate_slot_start(slot_start)
    slot_end = slot_start + timedelta(minutes=settings.APPOINTMENT_DURATION_MIN)
    async with uow:
        appt = await uow.appointments.get(appointment_id)
        if appt is None:
            raise NotFound("Appointment not found")
        appt = await uow.appointments.update_fields(
            appointment_id,
            start_at=slot_start,
            end_at=slot_end,
            status=AppointmentStatus.HELD,
        )
        assert appt is not None
        return to_view(appt)


async def hold_requested_appointment(
    uow: SqlAlchemyUnitOfWork,
    *,
    name: str,
    phone: str,
    reason_for_visit: str,
    notes: list[str],
    requested_slot_start: datetime,
) -> HoldAppointmentResult:
    requested_slot_start = _normalize_requested_start(requested_slot_start)

    try:
        async with uow:
            now = datetime.now(tz=requested_slot_start.tzinfo)
            scheduled_rows = await uow.appointments.list_future_by_phone(
                phone=phone,
                now=now,
                include_statuses=(AppointmentStatus.SCHEDULED,),
                ascending=True,
                limit=1,
            )
            held_rows = await uow.appointments.list_future_by_phone(
                phone=phone,
                now=now,
                include_statuses=(AppointmentStatus.HELD,),
                ascending=True,
                limit=1,
            )

            scheduled_appt = scheduled_rows[0] if scheduled_rows else None
            held_appt = held_rows[0] if held_rows else None

            slot = await _find_first_available_slot(
                uow,
                requested_start=requested_slot_start,
                exclude_appointment_id=held_appt.id if held_appt is not None else None,
            )

            effective_notes = _normalize_notes(notes)
            if not effective_notes:
                effective_notes = _notes_from_appointment(held_appt) or _notes_from_appointment(scheduled_appt)

            if held_appt is None:
                held_appt = await uow.appointments.create(
                    name=name,
                    phone=phone,
                    reason_for_visit=reason_for_visit,
                    start_at=slot.start_at,
                    end_at=slot.end_at,
                    notes=effective_notes,
                    status=AppointmentStatus.HELD,
                )
            else:
                held_appt = await uow.appointments.update_fields(
                    held_appt.id,
                    name=name,
                    phone=phone,
                    reason_for_visit=reason_for_visit,
                    start_at=slot.start_at,
                    end_at=slot.end_at,
                    notes=effective_notes,
                    status=AppointmentStatus.HELD,
                )

            assert held_appt is not None
            return HoldAppointmentResult(
                held_view=to_view(held_appt),
                scheduled_view=to_view(scheduled_appt) if scheduled_appt is not None else None,
            )
    except IntegrityError as e:
        raise SlotNotAvailable("That slot is already taken") from e


async def schedule_held_appointment(
    uow: SqlAlchemyUnitOfWork,
    *,
    held_appointment_id: int,
    scheduled_appointment_id: int | None = None,
) -> ScheduleAppointmentResult:
    async with uow:
        held_appt = await uow.appointments.get(held_appointment_id)
        if held_appt is None:
            raise NotFound("Appointment not found")
        if held_appt.status != AppointmentStatus.HELD:
            raise NotFound("Only HELD appointments can be scheduled")

        deleted_scheduled_view: AppointmentView | None = None
        if scheduled_appointment_id is not None and scheduled_appointment_id != held_appointment_id:
            scheduled_appt = await uow.appointments.get(scheduled_appointment_id)
            if scheduled_appt is not None and scheduled_appt.status == AppointmentStatus.SCHEDULED:
                deleted_scheduled_view = to_view(scheduled_appt)
                await uow.appointments.delete(scheduled_appointment_id)

        held_appt = await uow.appointments.update_fields(
            held_appointment_id,
            status=AppointmentStatus.SCHEDULED,
        )
        assert held_appt is not None
        return ScheduleAppointmentResult(
            scheduled_view=to_view(held_appt),
            deleted_scheduled_view=deleted_scheduled_view,
        )


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
        if not appt.status in (AppointmentStatus.HELD, AppointmentStatus.PENDING):
            raise NotFound("Only HELD or PENDING appointments can be deleted")
        return await uow.appointments.delete(appointment_id)


# async def update_held_appointment_details(
#         uow: SqlAlchemyUnitOfWork,
#         *,
#         appointment_id: int,
#         name: str,
#         phone: str,
#         reason_for_visit: str,
#         notes: list[str],
# ) -> AppointmentView:
#     async with uow:
#         appt = await uow.appointments.get(appointment_id)
#         if appt is None:
#             raise NotFound("Appointment not found")
#         if appt.status != AppointmentStatus.HELD:
#             raise NotFound("Only HELD appointments can be updated here")
#         appt = await uow.appointments.update_fields(
#             appointment_id,
#             name=name,
#             phone=phone,
#             reason_for_visit=reason_for_visit,
#             notes=notes,
#         )
#         assert appt is not None
#         return to_view(appt)


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


async def update_active_appointment_details(
    uow: SqlAlchemyUnitOfWork,
    *,
    appointment_id: int,
    name: str,
    phone: str,
    reason_for_visit: str,
    notes: list[str] | None = None,
) -> AppointmentView:
    async with uow:
        appt = await uow.appointments.get(appointment_id)
        if appt is None:
            raise NotFound("Appointment not found")
        if appt.status not in (AppointmentStatus.HELD, AppointmentStatus.SCHEDULED):
            raise NotFound("Only active appointments can be updated")
        fields = {
            "name": name,
            "phone": phone,
            "reason_for_visit": reason_for_visit,
        }
        if notes is not None:
            fields["notes"] = notes
        appt = await uow.appointments.update_fields(
            appointment_id,
            **fields,
        )
        assert appt is not None
        return to_view(appt)
