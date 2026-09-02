"""add track cover asset

Revision ID: 0007_track_cover_asset
Revises: 0006_algorithm_practice
Create Date: 2026-09-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_track_cover_asset"
down_revision: str | None = "0006_algorithm_practice"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tracks",
        sa.Column("cover_asset_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_tracks_cover_asset_id_assets",
        "tracks",
        "assets",
        ["cover_asset_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_tracks_cover_asset_id", "tracks", ["cover_asset_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_tracks_cover_asset_id", table_name="tracks")
    op.drop_constraint("fk_tracks_cover_asset_id_assets", "tracks", type_="foreignkey")
    op.drop_column("tracks", "cover_asset_id")
