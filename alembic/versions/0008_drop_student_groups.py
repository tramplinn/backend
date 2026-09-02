"""drop student groups

Revision ID: 0008_drop_student_groups
Revises: 0007_track_cover_asset
Create Date: 2026-09-02

Механизм учебных групп не использовался: ни одной записи не завели, а роли и
доступы держатся на users.role. Таблица и ссылка на неё удаляются целиком.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_drop_student_groups"
down_revision: str | None = "0007_track_cover_asset"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("users", "group_id")
    op.drop_table("student_groups")


def downgrade() -> None:
    op.create_table(
        "student_groups",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("year", sa.SmallInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_student_groups"),
        sa.UniqueConstraint("name", "year", name="uq_student_groups_name_year"),
    )
    op.add_column(
        "users",
        sa.Column("group_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_users_group_id_student_groups",
        "users",
        "student_groups",
        ["group_id"],
        ["id"],
        ondelete="SET NULL",
    )
    # Аудит-колонки и триггер восстанавливаем следом: без них откат 0002_audit_fields
    # упадёт на DROP TRIGGER несуществующего триггера.
    for column in ("created_by", "updated_by"):
        op.create_foreign_key(
            f"fk_student_groups_{column}_users",
            "student_groups",
            "users",
            [column],
            ["id"],
            ondelete="SET NULL",
        )
    op.execute(
        """
        CREATE TRIGGER trg_student_groups_fill_audit_fields
        BEFORE INSERT OR UPDATE ON student_groups
        FOR EACH ROW EXECUTE FUNCTION tramplin_fill_audit_fields()
        """,
    )
