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
    # A course can have several modules with NULL position (this migration's
    # upgrade() frees every soft-deleted module's position), so assigning them
    # all position=0 collides with uq_modules_course_id_position. Give each
    # one a distinct position appended after the course's current max instead.
    op.execute("""
        WITH max_pos AS (
            SELECT course_id, COALESCE(MAX(position), -1) AS max_position
            FROM modules
            GROUP BY course_id
        ),
        ranked AS (
            SELECT id, course_id,
                   ROW_NUMBER() OVER (PARTITION BY course_id ORDER BY id) AS rn
            FROM modules
            WHERE position IS NULL
        )
        UPDATE modules
        SET position = max_pos.max_position + ranked.rn
        FROM ranked
        JOIN max_pos ON max_pos.course_id = ranked.course_id
        WHERE modules.id = ranked.id
    """)
    # UPDATE above queues a check for uq_modules_course_id_position (deferrable),
    # which blocks the ALTER TABLE below unless flushed immediately.
    op.execute("SET CONSTRAINTS uq_modules_course_id_position IMMEDIATE")
    op.alter_column("modules", "position", existing_type=sa.Integer(), nullable=False)
