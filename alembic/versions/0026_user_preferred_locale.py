"""preferred interface locale in user profile

Revision ID: 0026_user_preferred_locale
Revises: 0025_cascade_algorithm_deletes
Create Date: 2026-10-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0026_user_preferred_locale"
down_revision: str | None = "0025_cascade_algorithm_deletes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("preferred_locale", sa.String(length=8), nullable=True))
    op.create_check_constraint(
        "ck_users_preferred_locale_allowed", "users", "preferred_locale IN ('ru', 'en')"
    )


def downgrade() -> None:
    op.drop_constraint("ck_users_preferred_locale_allowed", "users", type_="check")
    op.drop_column("users", "preferred_locale")
