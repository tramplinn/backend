"""company, university, interests and resume for user profiles

Revision ID: 0024_profile_directories
Revises: 0023_email_auth
Create Date: 2026-09-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0024_profile_directories"
down_revision: str | None = "0023_email_auth"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _dictionary_table(name: str, name_length: int) -> None:
    op.create_table(
        name,
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=name_length), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=f"fk_{name}_created_by_users",
            ondelete="SET NULL",
            use_alter=True,
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["users.id"],
            name=f"fk_{name}_updated_by_users",
            ondelete="SET NULL",
            use_alter=True,
        ),
        sa.PrimaryKeyConstraint("id", name=f"pk_{name}"),
    )
    op.create_index(f"uq_{name}_name_lower", name, [sa.text("lower(name)")], unique=True)


def upgrade() -> None:
    _dictionary_table("companies", 200)
    _dictionary_table("universities", 200)
    _dictionary_table("interests", 64)

    op.create_table(
        "user_interests",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("interest_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_user_interests_user_id_users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["interest_id"],
            ["interests.id"],
            name="fk_user_interests_interest_id_interests",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "interest_id", name="pk_user_interests"),
    )

    op.add_column("users", sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("users", sa.Column("university_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column(
        "users", sa.Column("resume_asset_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.create_foreign_key(
        "fk_users_company_id_companies",
        "users",
        "companies",
        ["company_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_users_university_id_universities",
        "users",
        "universities",
        ["university_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_users_resume_asset_id_assets",
        "users",
        "assets",
        ["resume_asset_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_users_company_id", "users", ["company_id"])
    op.create_index("ix_users_university_id", "users", ["university_id"])
    op.create_index("ix_users_resume_asset_id", "users", ["resume_asset_id"])


def downgrade() -> None:
    op.drop_index("ix_users_resume_asset_id", table_name="users")
    op.drop_index("ix_users_university_id", table_name="users")
    op.drop_index("ix_users_company_id", table_name="users")
    op.drop_constraint("fk_users_resume_asset_id_assets", "users", type_="foreignkey")
    op.drop_constraint("fk_users_university_id_universities", "users", type_="foreignkey")
    op.drop_constraint("fk_users_company_id_companies", "users", type_="foreignkey")
    op.drop_column("users", "resume_asset_id")
    op.drop_column("users", "university_id")
    op.drop_column("users", "company_id")

    op.drop_table("user_interests")
    op.drop_table("interests")
    op.drop_table("universities")
    op.drop_table("companies")
