"""add scheduled appointment snapshot to calls

Revision ID: e4b7e6c1d2a3
Revises: cf4a1a6d9b2d
Create Date: 2026-04-29 11:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "e4b7e6c1d2a3"
down_revision: Union[str, Sequence[str], None] = "cf4a1a6d9b2d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "calls",
        sa.Column("scheduled_appointment", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("calls", "scheduled_appointment")
