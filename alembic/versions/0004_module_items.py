"""single ordered list of module items

Порядок материалов модуля хранился в двух независимых нумерациях
(lessons.position и quizzes.position) плюс quizzes.lesson_id, а сама лента
собиралась на клиенте. Переносим порядок в одну таблицу: сервер становится
его владельцем, а lesson_id остаётся только смыслом «тест к этому уроку».

Revision ID: 0004_module_items
Revises: 0003_course_cover_asset
Create Date: 2026-08-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_module_items"
down_revision: str | None = "0003_course_cover_asset"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_quizzes_id_module_id",
        "quizzes",
        ["id", "module_id"],
    )
    op.create_table(
        "module_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("module_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("lesson_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("quiz_id", postgresql.UUID(as_uuid=True), nullable=True),
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
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_module_items"),
        sa.ForeignKeyConstraint(
            ["module_id"],
            ["modules.id"],
            name="fk_module_items_module_id_modules",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["lesson_id", "module_id"],
            ["lessons.id", "lessons.module_id"],
            name="fk_module_items_lesson_id_module_id_lessons",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["quiz_id", "module_id"],
            ["quizzes.id", "quizzes.module_id"],
            name="fk_module_items_quiz_id_module_id_quizzes",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name="fk_module_items_created_by_users",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["users.id"],
            name="fk_module_items_updated_by_users",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "num_nonnulls(lesson_id, quiz_id) = 1",
            name="module_items_one_target",
        ),
        sa.UniqueConstraint("lesson_id", name="uq_module_items_lesson_id"),
        sa.UniqueConstraint("quiz_id", name="uq_module_items_quiz_id"),
    )
    op.create_unique_constraint(
        "uq_module_items_module_id_position",
        "module_items",
        ["module_id", "position"],
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_index("ix_module_items_module_id", "module_items", ["module_id"])

    # Перенос существующего порядка ровно по той же логике, по которой ленту
    # собирал клиент: урок, следом привязанные к нему тесты, модульные — в конец.
    op.execute(
        """
        WITH ordered AS (
            SELECT
                l.module_id,
                l.id AS lesson_id,
                NULL::uuid AS quiz_id,
                l.position AS anchor_position,
                0 AS kind_order,
                0 AS item_position
            FROM lessons l
            UNION ALL
            SELECT
                q.module_id,
                NULL::uuid,
                q.id,
                COALESCE(l.position, 2147483647),
                CASE WHEN q.lesson_id IS NULL THEN 2 ELSE 1 END,
                q.position
            FROM quizzes q
            LEFT JOIN lessons l ON l.id = q.lesson_id
        )
        INSERT INTO module_items (id, module_id, position, lesson_id, quiz_id)
        SELECT
            COALESCE(lesson_id, quiz_id),
            module_id,
            (ROW_NUMBER() OVER (
                PARTITION BY module_id
                ORDER BY anchor_position, kind_order, item_position
            ) - 1)::int,
            lesson_id,
            quiz_id
        FROM ordered
        """
    )

    op.drop_constraint("uq_lessons_module_id_position", "lessons", type_="unique")
    op.drop_column("lessons", "position")
    op.drop_constraint("uq_quizzes_module_id_position", "quizzes", type_="unique")
    op.drop_column("quizzes", "position")


def downgrade() -> None:
    op.add_column("lessons", sa.Column("position", sa.Integer(), nullable=True))
    op.add_column("quizzes", sa.Column("position", sa.Integer(), nullable=True))
    op.execute(
        """
        UPDATE lessons SET position = ranked.rank FROM (
            SELECT i.lesson_id AS id,
                   (ROW_NUMBER() OVER (PARTITION BY i.module_id ORDER BY i.position) - 1)::int
                       AS rank
            FROM module_items i WHERE i.lesson_id IS NOT NULL
        ) AS ranked WHERE lessons.id = ranked.id
        """
    )
    op.execute(
        """
        UPDATE quizzes SET position = ranked.rank FROM (
            SELECT i.quiz_id AS id,
                   (ROW_NUMBER() OVER (PARTITION BY i.module_id ORDER BY i.position) - 1)::int
                       AS rank
            FROM module_items i WHERE i.quiz_id IS NOT NULL
        ) AS ranked WHERE quizzes.id = ranked.id
        """
    )
    op.alter_column("lessons", "position", nullable=False)
    op.alter_column("quizzes", "position", nullable=False)
    op.create_unique_constraint(
        "uq_lessons_module_id_position",
        "lessons",
        ["module_id", "position"],
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_unique_constraint(
        "uq_quizzes_module_id_position",
        "quizzes",
        ["module_id", "position"],
        deferrable=True,
        initially="DEFERRED",
    )
    op.drop_table("module_items")
    op.drop_constraint("uq_quizzes_id_module_id", "quizzes", type_="unique")
