"""allow email identities and add the email outbox

Revision ID: 0023_email_auth
Revises: 0022_gitlab_identity
Create Date: 2026-09-09
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0023_email_auth"
down_revision: str | None = "0022_gitlab_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
EMAIL_QUEUE = ("transactional", "bulk")
email_queue = postgresql.ENUM(*EMAIL_QUEUE, name="email_queue", create_type=False)


def _audit_columns() -> tuple[sa.Column[Any], ...]:
    return (
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", UUID, nullable=True),
        sa.Column("updated_by", UUID, nullable=True),
    )


def upgrade() -> None:
    op.execute("ALTER TYPE identity_provider ADD VALUE IF NOT EXISTS 'email'")

    postgresql.ENUM(*EMAIL_QUEUE, name="email_queue").create(op.get_bind())

    op.create_table(
        "email_job_outbox",
        sa.Column("id", UUID, nullable=False),
        sa.Column("to_email", sa.String(length=320), nullable=False),
        sa.Column("subject", sa.String(length=500), nullable=False),
        sa.Column("html_body", sa.Text(), nullable=False),
        sa.Column("text_body", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("queue", email_queue, nullable=False),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        *_audit_columns(),
        sa.PrimaryKeyConstraint("id", name="pk_email_job_outbox"),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name="fk_email_job_outbox_created_by_users",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["users.id"],
            name="fk_email_job_outbox_updated_by_users",
            ondelete="SET NULL",
        ),
    )


def downgrade() -> None:
    """identity_provider не откатываем (см. 0009): значение enum не удаляется."""
    op.drop_table("email_job_outbox")
    postgresql.ENUM(name="email_queue").drop(op.get_bind())
