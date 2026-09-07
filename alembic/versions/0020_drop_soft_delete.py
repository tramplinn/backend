"""drop soft delete: hard-delete content/algorithm entities again

Revision ID: 0020_drop_soft_delete
Revises: 0019_module_position_nullable
Create Date: 2026-09-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020_drop_soft_delete"
down_revision: str | None = "0019_module_position_nullable"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PARTIAL_UNIQUES: list[tuple[str, str, list[str], bool]] = [
    # (index name, table, columns, deferrable)
    (
        "uq_algorithm_test_cases_problem_id_position",
        "algorithm_test_cases",
        ["problem_id", "position"],
        True,
    ),
    ("uq_courses_slug", "courses", ["slug"], False),
    ("uq_lessons_module_id_slug", "lessons", ["module_id", "slug"], False),
    ("uq_modules_course_id_slug", "modules", ["course_id", "slug"], False),
    ("uq_news_slug", "news", ["slug"], False),
    ("uq_quizzes_module_id_slug", "quizzes", ["module_id", "slug"], False),
    ("uq_tracks_slug", "tracks", ["slug"], False),
    (
        "uq_user_identities_provider_provider_id",
        "user_identities",
        ["provider", "provider_id"],
        False,
    ),
    ("uq_user_identities_user_id_provider", "user_identities", ["user_id", "provider"], False),
]

_SOFT_DELETE_TABLES = [
    "algorithm_problems",
    "algorithm_test_cases",
    "courses",
    "feedback",
    "lessons",
    "modules",
    "news",
    "practice_sets",
    "quizzes",
    "tracks",
    "user_identities",
]


def upgrade() -> None:
    for name, table, columns, deferrable in _PARTIAL_UNIQUES:
        op.drop_index(name, table_name=table, postgresql_where=sa.text("NOT is_deleted"))
        if deferrable:
            op.create_unique_constraint(name, table, columns, deferrable=True, initially="DEFERRED")
        else:
            op.create_unique_constraint(name, table, columns)

    for table in _SOFT_DELETE_TABLES:
        op.drop_column(table, "deleted_at")
        op.drop_column(table, "is_deleted")

    op.execute("UPDATE modules SET position = 0 WHERE position IS NULL")
    # UPDATE above queues a check for uq_modules_course_id_position (deferrable),
    # which blocks the ALTER TABLE below unless flushed immediately.
    op.execute("SET CONSTRAINTS uq_modules_course_id_position IMMEDIATE")
    op.alter_column("modules", "position", existing_type=sa.Integer(), nullable=False)


def downgrade() -> None:
    op.alter_column("modules", "position", existing_type=sa.Integer(), nullable=True)

    for table in reversed(_SOFT_DELETE_TABLES):
        op.add_column(
            table, sa.Column("is_deleted", sa.Boolean(), server_default="false", nullable=False)
        )
        op.add_column(table, sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))

    for name, table, columns, _deferrable in reversed(_PARTIAL_UNIQUES):
        op.drop_constraint(name, table, type_="unique")
        op.create_index(
            name, table, columns, unique=True, postgresql_where=sa.text("NOT is_deleted")
        )
