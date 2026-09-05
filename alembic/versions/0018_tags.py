"""normalize topics into a shared tags table

Revision ID: 0018_tags
Revises: 0017_last_solution
Create Date: 2026-09-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
import uuid_utils.compat as uuid
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0018_tags"
down_revision: str | None = "0017_last_solution"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tags",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
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
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL", use_alter=True),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL", use_alter=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("uq_tags_name_lower", "tags", [sa.text("lower(name)")], unique=True)

    op.create_table(
        "course_tags",
        sa.Column("course_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tag_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["course_id"],
            ["courses.id"],
            name="fk_course_tags_course_id_courses",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tag_id"],
            ["tags.id"],
            name="fk_course_tags_tag_id_tags",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("course_id", "tag_id", name="pk_course_tags"),
    )
    op.create_table(
        "algorithm_problem_tags",
        sa.Column("problem_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tag_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["problem_id"],
            ["algorithm_problems.id"],
            name="fk_algorithm_problem_tags_problem_id_algorithm_problems",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tag_id"],
            ["tags.id"],
            name="fk_algorithm_problem_tags_tag_id_tags",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("problem_id", "tag_id", name="pk_algorithm_problem_tags"),
    )

    _backfill(op.get_bind())

    op.drop_column("courses", "topics")
    op.drop_column("algorithm_problems", "topics")


def _backfill(bind: sa.Connection) -> None:
    """Разбирает существующие ARRAY(topics) в нормализованные строки tags + связи.

    Регистр не различается (Python/python — один тег): первое встреченное написание
    остаётся отображаемым именем. Первая миграция с бэкфиллом в проекте — готового
    паттерна для копирования нет.
    """
    courses = sa.table(
        "courses",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("topics", postgresql.ARRAY(sa.String)),
    )
    problems = sa.table(
        "algorithm_problems",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("topics", postgresql.ARRAY(sa.String)),
    )
    tags_table = sa.table(
        "tags",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("name", sa.String),
    )
    course_tags_table = sa.table(
        "course_tags",
        sa.column("course_id", postgresql.UUID(as_uuid=True)),
        sa.column("tag_id", postgresql.UUID(as_uuid=True)),
    )
    problem_tags_table = sa.table(
        "algorithm_problem_tags",
        sa.column("problem_id", postgresql.UUID(as_uuid=True)),
        sa.column("tag_id", postgresql.UUID(as_uuid=True)),
    )

    tag_id_by_key: dict[str, uuid.UUID] = {}
    tag_name_by_key: dict[str, str] = {}

    def ensure_tag(raw: str) -> uuid.UUID | None:
        name = raw.strip()
        if not name:
            return None
        key = name.lower()
        if key not in tag_id_by_key:
            tag_id_by_key[key] = uuid.uuid7()
            tag_name_by_key[key] = name
        return tag_id_by_key[key]

    course_links: set[tuple[uuid.UUID, uuid.UUID]] = set()
    for row in bind.execute(sa.select(courses.c.id, courses.c.topics)):
        for raw in row.topics or []:
            tag_id = ensure_tag(raw)
            if tag_id is not None:
                course_links.add((row.id, tag_id))

    problem_links: set[tuple[uuid.UUID, uuid.UUID]] = set()
    for row in bind.execute(sa.select(problems.c.id, problems.c.topics)):
        for raw in row.topics or []:
            tag_id = ensure_tag(raw)
            if tag_id is not None:
                problem_links.add((row.id, tag_id))

    if tag_id_by_key:
        bind.execute(
            sa.insert(tags_table),
            [{"id": tag_id, "name": tag_name_by_key[key]} for key, tag_id in tag_id_by_key.items()],
        )
    if course_links:
        bind.execute(
            sa.insert(course_tags_table),
            [{"course_id": course_id, "tag_id": tag_id} for course_id, tag_id in course_links],
        )
    if problem_links:
        bind.execute(
            sa.insert(problem_tags_table),
            [{"problem_id": problem_id, "tag_id": tag_id} for problem_id, tag_id in problem_links],
        )


def downgrade() -> None:
    op.add_column(
        "courses",
        sa.Column("topics", postgresql.ARRAY(sa.String(64)), nullable=False, server_default="{}"),
    )
    op.add_column(
        "algorithm_problems",
        sa.Column("topics", postgresql.ARRAY(sa.String(64)), nullable=False, server_default="{}"),
    )

    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE courses c
            SET topics = COALESCE(sub.names, '{}')
            FROM (
                SELECT course_tags.course_id AS id, array_agg(tags.name ORDER BY tags.name) AS names
                FROM course_tags JOIN tags ON tags.id = course_tags.tag_id
                GROUP BY course_tags.course_id
            ) AS sub
            WHERE sub.id = c.id
            """
        )
    )
    bind.execute(
        sa.text(
            """
            UPDATE algorithm_problems p
            SET topics = COALESCE(sub.names, '{}')
            FROM (
                SELECT algorithm_problem_tags.problem_id AS id,
                       array_agg(tags.name ORDER BY tags.name) AS names
                FROM algorithm_problem_tags JOIN tags ON tags.id = algorithm_problem_tags.tag_id
                GROUP BY algorithm_problem_tags.problem_id
            ) AS sub
            WHERE sub.id = p.id
            """
        )
    )

    op.drop_table("algorithm_problem_tags")
    op.drop_table("course_tags")
    op.drop_table("tags")
