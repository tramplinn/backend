"""persist MCP OAuth grants and tokens

Revision ID: 0016_mcp_oauth
Revises: 0015_recommendation_embeddings
Create Date: 2026-09-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016_mcp_oauth"
down_revision: str | None = "0015_recommendation_embeddings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mcp_oauth_authorizations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=True),
        sa.Column("code_hash", sa.String(length=64), nullable=True),
        sa.Column("client_id", sa.String(length=128), nullable=False),
        sa.Column("redirect_uri", sa.String(length=512), nullable=False),
        sa.Column("state", sa.String(length=512), nullable=False),
        sa.Column("code_challenge", sa.String(length=128), nullable=False),
        sa.Column("scope", sa.String(length=128), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("request_expired_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("code_expired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code_hash"),
        sa.UniqueConstraint("request_hash"),
    )
    op.create_table(
        "mcp_oauth_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("access_hash", sa.String(length=64), nullable=True),
        sa.Column("refresh_hash", sa.String(length=64), nullable=True),
        sa.Column("access_expired_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("refresh_expired_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("access_hash"),
        sa.UniqueConstraint("refresh_hash"),
    )
    op.create_index(
        "ix_mcp_oauth_authorizations_request_expired_at",
        "mcp_oauth_authorizations",
        ["request_expired_at"],
    )
    op.create_index(
        "ix_mcp_oauth_tokens_access_expired_at",
        "mcp_oauth_tokens",
        ["access_expired_at"],
    )
    op.create_index(
        "ix_mcp_oauth_tokens_refresh_expired_at",
        "mcp_oauth_tokens",
        ["refresh_expired_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_mcp_oauth_tokens_refresh_expired_at", table_name="mcp_oauth_tokens")
    op.drop_index("ix_mcp_oauth_tokens_access_expired_at", table_name="mcp_oauth_tokens")
    op.drop_index(
        "ix_mcp_oauth_authorizations_request_expired_at",
        table_name="mcp_oauth_authorizations",
    )
    op.drop_table("mcp_oauth_tokens")
    op.drop_table("mcp_oauth_authorizations")
