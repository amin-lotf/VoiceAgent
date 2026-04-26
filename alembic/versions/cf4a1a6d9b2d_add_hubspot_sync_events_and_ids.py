"""add hubspot sync events and ids

Revision ID: cf4a1a6d9b2d
Revises: a1c9d4f7e821
Create Date: 2026-04-26 15:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "cf4a1a6d9b2d"
down_revision: Union[str, Sequence[str], None] = "a1c9d4f7e821"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("appointments", sa.Column("hubspot_contact_id", sa.String(length=100), nullable=True))
    op.add_column("appointments", sa.Column("hubspot_deal_id", sa.String(length=100), nullable=True))
    op.add_column("appointments", sa.Column("hubspot_ticket_id", sa.String(length=100), nullable=True))
    op.add_column("appointments", sa.Column("hubspot_note_id", sa.String(length=100), nullable=True))
    op.add_column("appointments", sa.Column("hubspot_last_synced_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("appointments", sa.Column("hubspot_sync_error", sa.Text(), nullable=True))

    op.create_table(
        "crm_sync_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("appointment_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING",
                "PROCESSING",
                "COMPLETED",
                "FAILED",
                name="crm_sync_status",
                create_constraint=True,
            ),
            nullable=False,
            server_default=sa.text("'PENDING'"),
        ),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["appointment_id"], ["appointments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "appointment_id",
            "provider",
            "event_type",
            name="uq_crm_sync_events_appointment_provider_event",
        ),
    )
    op.create_index(op.f("ix_crm_sync_events_appointment_id"), "crm_sync_events", ["appointment_id"], unique=False)
    op.create_index(op.f("ix_crm_sync_events_next_attempt_at"), "crm_sync_events", ["next_attempt_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_crm_sync_events_next_attempt_at"), table_name="crm_sync_events")
    op.drop_index(op.f("ix_crm_sync_events_appointment_id"), table_name="crm_sync_events")
    op.drop_table("crm_sync_events")

    op.drop_column("appointments", "hubspot_sync_error")
    op.drop_column("appointments", "hubspot_last_synced_at")
    op.drop_column("appointments", "hubspot_note_id")
    op.drop_column("appointments", "hubspot_ticket_id")
    op.drop_column("appointments", "hubspot_deal_id")
    op.drop_column("appointments", "hubspot_contact_id")
