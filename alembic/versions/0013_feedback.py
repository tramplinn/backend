"""feedback widget

Revision ID: 0013_feedback
Revises: 0012_news
Create Date: 2026-09-03
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013_feedback"
down_revision: str | None = "0012_news"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
FEEDBACK_STATUS = ("new", "resolved")
feedback_status = postgresql.ENUM(*FEEDBACK_STATUS, name="feedback_status", create_type=False)


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


def _audit_keys(table: str) -> tuple[sa.ForeignKeyConstraint, ...]:
    return (
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=f"fk_{table}_created_by_users", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"], ["users.id"], name=f"fk_{table}_updated_by_users", ondelete="SET NULL"
        ),
    )


def upgrade() -> None:
    postgresql.ENUM(*FEEDBACK_STATUS, name="feedback_status").create(op.get_bind())

    op.create_table(
        "feedback",
        sa.Column("id", UUID, nullable=False),
        # Автор уходит в NULL вместе с пользователем: сообщение переживает его.
        sa.Column("author_id", UUID, nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("page_path", sa.String(length=512), nullable=True),
        sa.Column("status", feedback_status, server_default="new", nullable=False),
        *_audit_columns(),
        sa.PrimaryKeyConstraint("id", name="pk_feedback"),
        sa.ForeignKeyConstraint(
            ["author_id"], ["users.id"], name="fk_feedback_author_id_users", ondelete="SET NULL"
        ),
        *_audit_keys("feedback"),
    )
    op.create_index("ix_feedback_status", "feedback", ["status"])

    op.create_table(
        "feedback_attachments",
        sa.Column("feedback_id", UUID, nullable=False),
        sa.Column("asset_id", UUID, nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        *_audit_columns(),
        sa.PrimaryKeyConstraint("feedback_id", "asset_id", name="pk_feedback_attachments"),
        sa.ForeignKeyConstraint(
            ["feedback_id"],
            ["feedback.id"],
            name="fk_feedback_attachments_feedback_id_feedback",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["assets.id"],
            name="fk_feedback_attachments_asset_id_assets",
            ondelete="CASCADE",
        ),
        *_audit_keys("feedback_attachments"),
    )
    op.create_unique_constraint(
        "uq_feedback_attachments_feedback_id_position",
        "feedback_attachments",
        ["feedback_id", "position"],
        deferrable=True,
        initially="DEFERRED",
    )


def downgrade() -> None:
    op.drop_table("feedback_attachments")
    op.drop_index("ix_feedback_status", table_name="feedback")
    op.drop_table("feedback")
    postgresql.ENUM(name="feedback_status").drop(op.get_bind())
