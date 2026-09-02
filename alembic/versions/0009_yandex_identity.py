"""allow yandex identities

Revision ID: 0009_yandex_identity
Revises: 0008_drop_student_groups
Create Date: 2026-09-02
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0009_yandex_identity"
down_revision: str | None = "0008_drop_student_groups"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE identity_provider ADD VALUE IF NOT EXISTS 'yandex'")


def downgrade() -> None:
    """Значение enum в Postgres не удаляется: пересобрать тип ради отката смысла нет."""
