"""add logs to calls

Revision ID: b6f6d26c4b31
Revises: e4b7e6c1d2a3
Create Date: 2026-05-01 14:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "b6f6d26c4b31"
down_revision: Union[str, Sequence[str], None] = "e4b7e6c1d2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "calls",
        sa.Column(
            "logs",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("calls", "logs")
