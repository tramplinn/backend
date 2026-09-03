"""public user profiles

Revision ID: 0014_user_profiles
Revises: 0013_feedback
Create Date: 2026-09-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_user_profiles"
down_revision: str | None = "0013_feedback"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("headline", sa.String(length=120), nullable=True))
    op.add_column("users", sa.Column("bio", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("specialty", sa.String(length=32), nullable=True))
    op.add_column("users", sa.Column("grade", sa.String(length=16), nullable=True))
    op.add_column("users", sa.Column("experience_years", sa.SmallInteger(), nullable=True))
    op.create_check_constraint(
        "ck_users_experience_years_range",
        "users",
        "experience_years >= 0 AND experience_years <= 80",
    )


def downgrade() -> None:
    op.drop_constraint("ck_users_experience_years_range", "users", type_="check")
    op.drop_column("users", "experience_years")
    op.drop_column("users", "grade")
    op.drop_column("users", "specialty")
    op.drop_column("users", "bio")
    op.drop_column("users", "headline")
