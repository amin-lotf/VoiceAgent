from datetime import datetime
from typing import Any
from sqlalchemy import (
    String, Text, DateTime, Enum, ForeignKey, Integer
)
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import ExcludeConstraint

from .base import Base
from ..types import AppointmentStatus, CrmSyncStatus


class Appointment(Base):
    __tablename__ = "appointments"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Nullable for pending requests before a slot is chosen
    start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    status: Mapped[AppointmentStatus] = mapped_column(
        Enum(
            AppointmentStatus,
            name="appointment_status",
            native_enum=True,
            create_constraint=True,
        ),
        nullable=False,
    )

    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    reason_for_visit: Mapped[str | None] = mapped_column(Text, nullable=True)

    notes: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    hubspot_contact_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    hubspot_deal_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    hubspot_ticket_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    hubspot_note_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    hubspot_last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    hubspot_sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        sa.CheckConstraint(
            """
            (
                status = 'PENDING'
                OR (start_at IS NOT NULL AND end_at IS NOT NULL AND end_at > start_at)
            )
            """,
            name="ck_appointments_time_required_for_scheduled_states",
        ),
        ExcludeConstraint(
            (sa.func.tstzrange(sa.column("start_at"), sa.column("end_at"), "[)"), "&&"),
            where=sa.text("status IN ('HELD', 'SCHEDULED')"),
            using="gist",
            name="excl_appointments_no_overlap_active",
        ),
    )


class CrmSyncEvent(Base):
    __tablename__ = "crm_sync_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    appointment_id: Mapped[int] = mapped_column(
        ForeignKey("appointments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    status: Mapped[CrmSyncStatus] = mapped_column(
        Enum(
            CrmSyncStatus,
            name="crm_sync_status",
            native_enum=True,
            create_constraint=True,
        ),
        nullable=False,
        server_default=text("'PENDING'"),
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        sa.UniqueConstraint(
            "appointment_id",
            "provider",
            "event_type",
            name="uq_crm_sync_events_appointment_provider_event",
        ),
    )


class CallRecord(Base):
    __tablename__ = "calls"

    id: Mapped[int] = mapped_column(primary_key=True)
    call_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    final_status: Mapped[str | None] = mapped_column(String(100), nullable=True)
    scheduled_appointment: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    turns: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
