from datetime import datetime
from sqlalchemy import (
    String, Text, DateTime, Enum
)
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import ExcludeConstraint

from .base import Base
from ..types import AppointmentStatus


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