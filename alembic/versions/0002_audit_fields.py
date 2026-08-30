"""add audit fields and timestamp triggers to every entity

Revision ID: 0002_audit_fields
Revises: 0001_initial
Create Date: 2026-08-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_audit_fields"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (
    "assets",
    "courses",
    "student_groups",
    "tracks",
    "modules",
    "tracks_course",
    "users",
    "lessons",
    "module_deps",
    "refresh_tokens",
    "user_identities",
    "interview_cards",
    "lesson_progress",
    "quizzes",
    "quiz_attempts",
    "quiz_questions",
)


def upgrade() -> None:
    timestamp = sa.DateTime(timezone=True)
    user_id = postgresql.UUID(as_uuid=True)

    for table in TABLES:
        if table != "user_identities":
            op.add_column(
                table,
                sa.Column("created_at", timestamp, server_default=sa.text("now()"), nullable=False),
            )
        op.add_column(
            table,
            sa.Column("updated_at", timestamp, server_default=sa.text("now()"), nullable=False),
        )
        op.add_column(table, sa.Column("created_by", user_id, nullable=True))
        op.add_column(table, sa.Column("updated_by", user_id, nullable=True))

    for table in TABLES:
        op.create_foreign_key(
            f"fk_{table}_created_by_users",
            table,
            "users",
            ["created_by"],
            ["id"],
            ondelete="SET NULL",
        )
        op.create_foreign_key(
            f"fk_{table}_updated_by_users",
            table,
            "users",
            ["updated_by"],
            ["id"],
            ondelete="SET NULL",
        )

    op.execute(
        """
        CREATE FUNCTION tramplin_fill_audit_fields()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            actor_id uuid := NULLIF(
                current_setting('tramplin.current_user_id', true), ''
            )::uuid;
        BEGIN
            IF TG_OP = 'INSERT' THEN
                NEW.created_at := COALESCE(NEW.created_at, CURRENT_TIMESTAMP);
                NEW.updated_at := COALESCE(NEW.updated_at, NEW.created_at);
                NEW.created_by := COALESCE(NEW.created_by, NEW.updated_by, actor_id);
                NEW.updated_by := COALESCE(NEW.updated_by, NEW.created_by, actor_id);
            ELSE
                NEW.created_at := OLD.created_at;
                NEW.updated_at := CURRENT_TIMESTAMP;
                IF NEW.updated_by IS NOT DISTINCT FROM OLD.updated_by THEN
                    NEW.updated_by := COALESCE(actor_id, OLD.updated_by);
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$
        """,
    )

    for table in TABLES:
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_fill_audit_fields
            BEFORE INSERT OR UPDATE ON {table}
            FOR EACH ROW EXECUTE FUNCTION tramplin_fill_audit_fields()
            """,
        )


def downgrade() -> None:
    for table in reversed(TABLES):
        op.execute(f"DROP TRIGGER trg_{table}_fill_audit_fields ON {table}")

    op.execute("DROP FUNCTION tramplin_fill_audit_fields()")

    for table in reversed(TABLES):
        op.drop_constraint(f"fk_{table}_updated_by_users", table, type_="foreignkey")
        op.drop_constraint(f"fk_{table}_created_by_users", table, type_="foreignkey")
        op.drop_column(table, "updated_by")
        op.drop_column(table, "created_by")
        op.drop_column(table, "updated_at")
        if table != "user_identities":
            op.drop_column(table, "created_at")
