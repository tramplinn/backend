"""make module position nullable, free it on soft delete

Revision ID: 0019_module_position_nullable
Revises: 0018_tags
Create Date: 2026-09-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019_module_position_nullable"
down_revision: str | None = "0018_tags"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("modules", "position", existing_type=sa.Integer(), nullable=True)
    # uq_modules_course_id_position не исключает удалённые строки (partial index
    # нельзя сделать deferrable), поэтому уже удалённые модули могли навсегда
    # занять чью-то позицию в курсе — освобождаем их.
    op.execute("UPDATE modules SET position = NULL WHERE is_deleted")


def downgrade() -> None:
    op.execute("UPDATE modules SET position = 0 WHERE position IS NULL")
    op.alter_column("modules", "position", existing_type=sa.Integer(), nullable=False)
