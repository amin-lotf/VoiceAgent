"""add calls table

Revision ID: a1c9d4f7e821
Revises: 4d9a536b51a9
Create Date: 2026-04-15 13:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "a1c9d4f7e821"
down_revision: Union[str, Sequence[str], None] = "4d9a536b51a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "calls",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("call_id", sa.String(length=255), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("final_status", sa.String(length=100), nullable=True),
        sa.Column("turns", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("call_id"),
    )
    op.create_index(op.f("ix_calls_call_id"), "calls", ["call_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_calls_call_id"), table_name="calls")
    op.drop_table("calls")
