"""add course cover asset

Revision ID: 0003_course_cover_asset
Revises: 0002_audit_fields
Create Date: 2026-08-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_course_cover_asset"
down_revision: str | None = "0002_audit_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "courses",
        sa.Column("cover_asset_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_courses_cover_asset_id_assets",
        "courses",
        "assets",
        ["cover_asset_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_courses_cover_asset_id", "courses", ["cover_asset_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_courses_cover_asset_id", table_name="courses")
    op.drop_constraint("fk_courses_cover_asset_id_assets", "courses", type_="foreignkey")
    op.drop_column("courses", "cover_asset_id")
