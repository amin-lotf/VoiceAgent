import enum
from datetime import datetime
from sqlalchemy import (
    String, Text, DateTime, Enum, CheckConstraint, Index
)
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import ExcludeConstraint
from sqlalchemy.dialects.postgresql import TSRANGE  # not used; using tstzrange() via text

from .base import Base
from ..types import AppointmentStatus


class Appointment(Base):
    __tablename__ = "appointments"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Availability source of truth:
    start_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)

    status: Mapped[AppointmentStatus] = mapped_column(
        Enum(
            AppointmentStatus,
            name="appointment_status",
            native_enum=True,
            create_constraint=True,
        ),
        nullable=False,
    )

    name: Mapped[str | None] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(50))
    reason_for_visit: Mapped[str | None] = mapped_column(Text)


    # notes: list[str]
    notes: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        sa.CheckConstraint("end_at > start_at", name="ck_appointments_end_after_start"),

        ExcludeConstraint(
            (sa.func.tstzrange(start_at, end_at, "[)"), "&&"),
            where=sa.text(f"status IN ({AppointmentStatus.HELD}, {AppointmentStatus.SCHEDULED})"),
            using="gist",
            name="excl_appointments_no_overlap_active",
        ),
    )