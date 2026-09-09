"""allow gitlab identities

Revision ID: 0022_gitlab_identity
Revises: 0021_algorithm_problem_slug
Create Date: 2026-09-09
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0022_gitlab_identity"
down_revision: str | None = "0021_algorithm_problem_slug"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE identity_provider ADD VALUE IF NOT EXISTS 'gitlab'")


def downgrade() -> None:
    """Значение enum в Postgres не удаляется: пересобрать тип ради отката смысла нет."""
