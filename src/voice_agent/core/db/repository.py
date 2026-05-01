from datetime import datetime
from typing import Any, Optional, Sequence

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from voice_agent.common import utcnow
from voice_agent.core.db.models import Appointment, CallRecord, CrmSyncEvent
from voice_agent.core.types import AppointmentStatus, CrmSyncStatus, TimeSlot


class SqlAlchemyAppointmentRepository:
    """
    Works with ORM models only.
    No commit/rollback here.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, appointment_id: int) -> Optional[Appointment]:
        stmt = sa.select(Appointment).where(Appointment.id == appointment_id)
        res = await self._session.execute(stmt)
        return res.scalar_one_or_none()

    async def add(self, appt: Appointment) -> Appointment:
        self._session.add(appt)
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

    async def update_fields(self, appointment_id: int, **fields) -> Optional[Appointment]:
        """
        Loads the row, mutates fields, flushes.
        Returns updated model (or None if not found).
        """
        appt = await self.get(appointment_id)
        if appt is None:
            return None

        for key, value in fields.items():
            if not hasattr(appt, key):
                raise ValueError(f"Appointment has no field: {key}")
            setattr(appt, key, value)

        await self._session.flush()
        await self._session.refresh(appt)
        return appt

    async def set_status(self, appointment_id: int, status: AppointmentStatus) -> Optional[Appointment]:
        return await self.update_fields(appointment_id, status=status)

    async def list_future_by_phone(
        self,
        *,
        phone: str,
        now: datetime | None = None,
        include_statuses: Sequence[AppointmentStatus] | None = None,
        limit: int = 50,
        ascending: bool = True,
    ) -> list[Appointment]:
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

        merged: list[tuple[datetime, datetime]] = []
        for busy_item in busy:
            start_at = max(busy_item.start_at, start_range)
            end_at = min(busy_item.end_at, end_range)
            if end_at <= start_at:
                continue
            if not merged or start_at > merged[-1][1]:
                merged.append((start_at, end_at))
            else:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end_at))

        free_intervals: list[tuple[datetime, datetime]] = []
        cursor = start_range
        for start_at, end_at in merged:
            if cursor < start_at:
                free_intervals.append((cursor, start_at))
            cursor = max(cursor, end_at)
        if cursor < end_range:
            free_intervals.append((cursor, end_range))

        step = sa.text("")
        _ = step

        slot_seconds = slot_minutes * 60
        out: list[TimeSlot] = []
        for start_at, end_at in free_intervals:
            current = start_at
            while (current.timestamp() + slot_seconds) <= end_at.timestamp():
                next_dt = datetime.fromtimestamp(current.timestamp() + slot_seconds, tz=current.tzinfo)
                out.append(TimeSlot(start_at=current, end_at=next_dt))
                current = next_dt

        return out


class SqlAlchemyCallRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _normalize_scheduled_appointment(
        scheduled_appointment: dict | None,
    ) -> dict | None:
        snapshot = dict(scheduled_appointment or {})
        if not snapshot or snapshot.get("id") is None:
            return None
        return snapshot

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
            logs=[],
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
        total_tokens: int | None = None,
        total_delay_s: float | None = None,
        first_token_delay_s: float | None = None,
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
                "total_tokens": total_tokens,
                "total_delay_s": total_delay_s,
                "first_token_delay_s": first_token_delay_s,
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
        scheduled_appointment: dict | None = None,
        ended_at: datetime | None = None,
        overwrite_existing: bool = False,
    ) -> CallRecord:
        call = await self.create_or_get(call_id=call_id)
        if call.ended_at is not None and not overwrite_existing:
            return call

        call.ended_at = ended_at or utcnow()
        if final_status and (overwrite_existing or not call.final_status):
            call.final_status = final_status
        normalized_appointment = self._normalize_scheduled_appointment(scheduled_appointment)
        if normalized_appointment is not None:
            call.scheduled_appointment = normalized_appointment

        await self._session.flush()
        await self._session.refresh(call)
        return call

    async def update_status(
        self,
        *,
        call_id: str,
        final_status: str | None,
        scheduled_appointment: dict | None = None,
        overwrite_existing: bool = False,
    ) -> CallRecord:
        call = await self.create_or_get(call_id=call_id)
        status = (final_status or "").strip()
        normalized_appointment = self._normalize_scheduled_appointment(scheduled_appointment)
        if normalized_appointment is None and not status:
            return call

        if status and (overwrite_existing or not call.final_status):
            call.final_status = status
        if normalized_appointment is not None:
            call.scheduled_appointment = normalized_appointment

        await self._session.flush()
        await self._session.refresh(call)

        return call

    async def append_logs(
        self,
        *,
        call_id: str,
        logs: Sequence[dict[str, Any]],
    ) -> CallRecord:
        call = await self.create_or_get(call_id=call_id)
        next_logs = [dict(item) for item in logs if isinstance(item, dict)]
        if not next_logs:
            return call

        stored_logs = list(call.logs or [])
        stored_logs.extend(next_logs)
        call.logs = stored_logs

        await self._session.flush()
        await self._session.refresh(call)
        return call


class SqlAlchemyCrmSyncEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, event_id: int) -> Optional[CrmSyncEvent]:
        stmt = sa.select(CrmSyncEvent).where(CrmSyncEvent.id == event_id)
        res = await self._session.execute(stmt)
        return res.scalar_one_or_none()

    async def get_for_appointment(
        self,
        *,
        appointment_id: int,
        provider: str,
        event_type: str,
    ) -> Optional[CrmSyncEvent]:
        stmt = sa.select(CrmSyncEvent).where(
            CrmSyncEvent.appointment_id == appointment_id,
            CrmSyncEvent.provider == provider,
            CrmSyncEvent.event_type == event_type,
        )
        res = await self._session.execute(stmt)
        return res.scalar_one_or_none()

    async def enqueue(
        self,
        *,
        appointment_id: int,
        provider: str,
        event_type: str,
        payload: dict | None = None,
        next_attempt_at: datetime | None = None,
    ) -> CrmSyncEvent:
        existing = await self.get_for_appointment(
            appointment_id=appointment_id,
            provider=provider,
            event_type=event_type,
        )
        if existing is not None:
            existing.payload = dict(payload or existing.payload or {})
            existing.status = CrmSyncStatus.PENDING
            existing.attempt_count = 0
            existing.locked_at = None
            existing.last_error = None
            existing.processed_at = None
            existing.next_attempt_at = next_attempt_at or utcnow()
            await self._session.flush()
            await self._session.refresh(existing)
            return existing

        event = CrmSyncEvent(
            appointment_id=appointment_id,
            provider=provider,
            event_type=event_type,
            payload=dict(payload or {}),
            status=CrmSyncStatus.PENDING,
            next_attempt_at=next_attempt_at or utcnow(),
        )
        self._session.add(event)
        await self._session.flush()
        await self._session.refresh(event)
        return event

    async def claim_due(
        self,
        *,
        now: datetime | None = None,
        limit: int = 10,
        stale_before: datetime | None = None,
        provider: str | None = None,
    ) -> list[CrmSyncEvent]:
        now = now or utcnow()
        stale_before = stale_before or now

        due_filter = sa.or_(
            sa.and_(
                CrmSyncEvent.status.in_((CrmSyncStatus.PENDING, CrmSyncStatus.FAILED)),
                CrmSyncEvent.next_attempt_at <= now,
            ),
            sa.and_(
                CrmSyncEvent.status == CrmSyncStatus.PROCESSING,
                CrmSyncEvent.locked_at.is_not(None),
                CrmSyncEvent.locked_at <= stale_before,
            ),
        )

        stmt = (
            sa.select(CrmSyncEvent)
            .where(due_filter)
            .order_by(CrmSyncEvent.next_attempt_at.asc(), CrmSyncEvent.id.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        if provider:
            stmt = stmt.where(CrmSyncEvent.provider == provider)

        res = await self._session.execute(stmt)
        rows = list(res.scalars().all())
        for row in rows:
            row.status = CrmSyncStatus.PROCESSING
            row.locked_at = now
            row.last_attempt_at = now
            row.attempt_count = int(row.attempt_count or 0) + 1

        if rows:
            await self._session.flush()
            for row in rows:
                await self._session.refresh(row)
        return rows

    async def mark_completed(self, event_id: int, *, processed_at: datetime | None = None) -> Optional[CrmSyncEvent]:
        event = await self.get(event_id)
        if event is None:
            return None
        finished_at = processed_at or utcnow()
        event.status = CrmSyncStatus.COMPLETED
        event.locked_at = None
        event.last_error = None
        event.processed_at = finished_at
        event.next_attempt_at = finished_at
        await self._session.flush()
        await self._session.refresh(event)
        return event

    async def mark_failed(
        self,
        event_id: int,
        *,
        last_error: str,
        next_attempt_at: datetime,
    ) -> Optional[CrmSyncEvent]:
        event = await self.get(event_id)
        if event is None:
            return None
        event.status = CrmSyncStatus.FAILED
        event.locked_at = None
        event.last_error = last_error
        event.next_attempt_at = next_attempt_at
        event.processed_at = None
        await self._session.flush()
        await self._session.refresh(event)
        return event
