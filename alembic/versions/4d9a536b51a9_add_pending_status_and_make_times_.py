"""add pending status and make times nullable

Revision ID: 4d9a536b51a9
Revises: 87ce1e68ff9c
Create Date: 2026-03-19 16:42:18.766715

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4d9a536b51a9'
down_revision: Union[str, Sequence[str], None] = '87ce1e68ff9c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    # 1) Add enum value in its own autocommitted block
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE appointment_status ADD VALUE IF NOT EXISTS 'PENDING'")

    # 2) Now it is safe to use the new enum value
    op.alter_column(
        "appointments",
        "start_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=True,
    )

    op.alter_column(
        "appointments",
        "end_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=True,
    )

    # optional: normalize old rows before adding check constraint
    op.execute("""
        UPDATE appointments
        SET status = 'PENDING'
        WHERE start_at IS NULL OR end_at IS NULL
    """)

    op.execute("""
        ALTER TABLE appointments
        DROP CONSTRAINT IF EXISTS excl_appointments_no_overlap_active
    """)

    op.execute("""
        ALTER TABLE appointments
        ADD CONSTRAINT excl_appointments_no_overlap_active
        EXCLUDE USING gist (
            tstzrange(start_at, end_at, '[)') WITH &&
        )
        WHERE (status IN ('HELD', 'SCHEDULED'))
    """)

    op.execute("""
        ALTER TABLE appointments
        ADD CONSTRAINT ck_appointments_time_required_for_scheduled_states
        CHECK (
            status = 'PENDING'
            OR (start_at IS NOT NULL AND end_at IS NOT NULL AND end_at > start_at)
        )
    """)


def downgrade():
    op.execute("""
        ALTER TABLE appointments
        DROP CONSTRAINT IF EXISTS ck_appointments_time_required_for_scheduled_states
    """)

    op.execute("""
        ALTER TABLE appointments
        DROP CONSTRAINT IF EXISTS excl_appointments_no_overlap_active
    """)

    op.alter_column(
        "appointments",
        "start_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
    )

    op.alter_column(
        "appointments",
        "end_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
    )

    op.execute("""
        ALTER TABLE appointments
        ADD CONSTRAINT excl_appointments_no_overlap_active
        EXCLUDE USING gist (
            tstzrange(start_at, end_at, '[)') WITH &&
        )
        WHERE (status IN ('HELD', 'SCHEDULED'))
    """)

    # enum value removal is not supported cleanly in postgres

