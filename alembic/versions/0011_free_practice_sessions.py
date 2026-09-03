"""free practice sessions

Revision ID: 0011_free_practice_sessions
Revises: 0010_drop_track_cover_asset
Create Date: 2026-09-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011_free_practice_sessions"
down_revision: str | None = "0010_drop_track_cover_asset"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # NULL — сессия тренажёра: задача решается вне набора практики.
    op.alter_column(
        "practice_sessions",
        "practice_set_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=True,
    )
    op.create_index(
        "ix_algorithm_problems_status",
        "algorithm_problems",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_algorithm_problems_status", table_name="algorithm_problems")
    op.execute(sa.text("DELETE FROM practice_sessions WHERE practice_set_id IS NULL"))
    op.alter_column(
        "practice_sessions",
        "practice_set_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )
