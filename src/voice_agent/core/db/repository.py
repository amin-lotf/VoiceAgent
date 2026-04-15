from datetime import datetime
from typing import Optional, Sequence

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from voice_agent.common import utcnow
from voice_agent.core.db.models import Appointment, CallRecord
from voice_agent.core.types import TimeSlot, AppointmentStatus


class SqlAlchemyAppointmentRepository:
    """
    Works with ORM models only.
    No commit/rollback here.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ---- basic CRUD ----

    async def get(self, appointment_id: int) -> Optional[Appointment]:
        stmt = sa.select(Appointment).where(Appointment.id == appointment_id)
        res = await self._session.execute(stmt)
        return res.scalar_one_or_none()

    async def add(self, appt: Appointment) -> Appointment:
        self._session.add(appt)
        # flush so appt.id is available without committing
        await self._session.flush()
        return appt

    async def delete(self, appointment_id: int) -> bool:
        appt = await self.get(appointment_id)
        if appt is None:
            return False
        await self._session.delete(appt)
        await self._session.flush()
        return True

    async def create(
        self,
        *,
        name: str | None,
        phone: str | None,
        reason_for_visit: str | None,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        notes: list[str] | None = None,
        status: AppointmentStatus = AppointmentStatus.HELD,
    ) -> Appointment:
        appt = Appointment(
            name=name,
            phone=phone,
            reason_for_visit=reason_for_visit,
            start_at=start_at,
            end_at=end_at,
            notes=notes or [],
            status=status,
        )
        return await self.add(appt)

    async def update_fields(
        self,
        appointment_id: int,
        **fields,
    ) -> Optional[Appointment]:
        """
        Loads the row, mutates fields, flushes.
        Returns updated model (or None if not found).
        """
        appt = await self.get(appointment_id)
        if appt is None:
            return None

        for k, v in fields.items():
            if not hasattr(appt, k):
                raise ValueError(f"Appointment has no field: {k}")
            setattr(appt, k, v)

        await self._session.flush()
        # Ensure server-updated/default columns are loaded (e.g. updated_at)
        # so later attribute access does not trigger implicit async lazy IO.
        await self._session.refresh(appt)
        return appt

    async def set_status(self, appointment_id: int, status: AppointmentStatus) -> Optional[Appointment]:
        return await self.update_fields(appointment_id, status=status)

    # ---- queries you asked for ----

    async def list_future_by_phone(
        self,
        *,
        phone: str,
        now: datetime | None = None,
        include_statuses: Sequence[AppointmentStatus] | None = None,
        limit: int = 50,
        ascending: bool = True,
    ) -> list[Appointment]:
        """
        Future appointments for a specific phone number, from now onward.

        By default includes all statuses; you can restrict via include_statuses.
        """
        now = now or utcnow()

        stmt = sa.select(Appointment).where(
            Appointment.phone == phone,
            Appointment.start_at >= now,
        )

        if include_statuses:
            stmt = stmt.where(Appointment.status.in_(include_statuses))

        order = Appointment.start_at.asc() if ascending else Appointment.start_at.desc()
        stmt = stmt.order_by(order).limit(limit)

        res = await self._session.execute(stmt)
        return list(res.scalars().all())

    async def list_busy_between(
        self,
        *,
        start_range: datetime,
        end_range: datetime,
        active_statuses: Sequence[AppointmentStatus] = (AppointmentStatus.HELD, AppointmentStatus.SCHEDULED),
        exclude_appointment_id: int | None = None,
    ) -> list[Appointment]:
        """
        Returns appointments that overlap [start_range, end_range)
        and are considered "blocking" for availability (default: HELD, SCHEDULED).
        """
        # overlap condition for half-open intervals:
        # busy.start < end_range AND busy.end > start_range
        stmt = (
            sa.select(Appointment)
            .where(
                Appointment.status.in_(active_statuses),
                Appointment.start_at < end_range,
                Appointment.end_at > start_range,
            )
            .order_by(Appointment.start_at.asc())
        )
        if exclude_appointment_id is not None:
            stmt = stmt.where(Appointment.id != exclude_appointment_id)
        res = await self._session.execute(stmt)
        return list(res.scalars().all())

    async def list_free_slots_between(
        self,
        *,
        start_range: datetime,
        end_range: datetime,
        slot_minutes: int = 30,
        active_statuses: Sequence[AppointmentStatus] = (AppointmentStatus.HELD, AppointmentStatus.SCHEDULED),
        clamp_to_now: bool = True,
        now: datetime | None = None,
    ) -> list[TimeSlot]:
        """
        Computes free slots within [start_range, end_range) by subtracting busy intervals.

        Notes:
        - returns discrete slots of fixed length `slot_minutes`
        - uses simple interval subtraction (no calendars/working hours)
        - if clamp_to_now=True, start_range is bumped to max(start_range, now)
        """
        if end_range <= start_range:
            return []

        now = now or utcnow()
        if clamp_to_now and start_range < now:
            start_range = now
            if end_range <= start_range:
                return []

        busy = await self.list_busy_between(
            start_range=start_range,
            end_range=end_range,
            active_statuses=active_statuses,
        )

        # merge busy intervals (they shouldn't overlap due to your constraint,
        # but HELD+SCHEDULED across edges can still benefit from merging)
        merged: list[tuple[datetime, datetime]] = []
        for b in busy:
            s, e = max(b.start_at, start_range), min(b.end_at, end_range)
            if e <= s:
                continue
            if not merged or s > merged[-1][1]:
                merged.append((s, e))
            else:
                merged[-1] = (merged[-1][0], max(merged[-1][1], e))

        # free intervals = gaps between merged busy blocks
        free_intervals: list[tuple[datetime, datetime]] = []
        cursor = start_range
        for s, e in merged:
            if cursor < s:
                free_intervals.append((cursor, s))
            cursor = max(cursor, e)
        if cursor < end_range:
            free_intervals.append((cursor, end_range))

        # chop free intervals into fixed-size slots
        step = sa.text("")  # dummy to avoid unused import lint in some setups
        _ = step

        slot_seconds = slot_minutes * 60
        out: list[TimeSlot] = []
        for s, e in free_intervals:
            # align to the next slot boundary relative to s itself (simple)
            t = s
            while (t.timestamp() + slot_seconds) <= e.timestamp():
                t2 = datetime.fromtimestamp(t.timestamp() + slot_seconds, tz=t.tzinfo)
                out.append(TimeSlot(start_at=t, end_at=t2))
                t = t2

        return out


class SqlAlchemyCallRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_call_id(self, call_id: str) -> Optional[CallRecord]:
        stmt = sa.select(CallRecord).where(CallRecord.call_id == call_id)
        res = await self._session.execute(stmt)
        return res.scalar_one_or_none()

    async def create_or_get(
        self,
        *,
        call_id: str,
        started_at: datetime | None = None,
    ) -> CallRecord:
        call = await self.get_by_call_id(call_id)
        if call is not None:
            return call

        call = CallRecord(
            call_id=call_id,
            started_at=started_at or utcnow(),
            turns=[],
        )
        self._session.add(call)
        await self._session.flush()
        return call

    async def list_recent(self, *, limit: int = 50) -> list[CallRecord]:
        stmt = (
            sa.select(CallRecord)
            .order_by(CallRecord.started_at.desc(), CallRecord.id.desc())
            .limit(limit)
        )
        res = await self._session.execute(stmt)
        return list(res.scalars().all())

    async def append_turn(
        self,
        *,
        call_id: str,
        role: str,
        content: str,
        created_at: datetime | None = None,
    ) -> CallRecord:
        text = (content or "").strip()
        call = await self.create_or_get(call_id=call_id)
        if not text:
            return call

        turns = list(call.turns or [])
        if turns:
            last = turns[-1]
            if last.get("role") == role and (last.get("content") or "").strip() == text:
                return call

        turns.append(
            {
                "role": role,
                "content": text,
                "created_at": (created_at or utcnow()).isoformat(),
            }
        )
        call.turns = turns
        await self._session.flush()
        await self._session.refresh(call)
        return call

    async def finish(
        self,
        *,
        call_id: str,
        final_status: str | None = None,
        ended_at: datetime | None = None,
        overwrite_existing: bool = False,
    ) -> CallRecord:
        call = await self.create_or_get(call_id=call_id)
        if call.ended_at is not None and not overwrite_existing:
            return call

        call.ended_at = ended_at or utcnow()
        if final_status and (overwrite_existing or not call.final_status):
            call.final_status = final_status

        await self._session.flush()
        await self._session.refresh(call)
        return call
