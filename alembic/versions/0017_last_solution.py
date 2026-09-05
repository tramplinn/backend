"""store last accepted solution on algorithm progress

Revision ID: 0017_last_solution
Revises: 0016_mcp_oauth
Create Date: 2026-09-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_last_solution"
down_revision: str | None = "0016_mcp_oauth"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "algorithm_progress",
        sa.Column("last_solution_language", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "algorithm_progress",
        sa.Column("last_solution_code", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("algorithm_progress", "last_solution_code")
    op.drop_column("algorithm_progress", "last_solution_language")
