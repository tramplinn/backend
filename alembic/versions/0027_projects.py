"""user projects and public profile layout

Revision ID: 0027_projects
Revises: 0026_user_preferred_locale
Create Date: 2026-10-03
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0027_projects"
down_revision: str | None = "0026_user_preferred_locale"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
ENUMS: dict[str, tuple[str, ...]] = {
    "project_status": ("idea", "planning", "in_progress", "paused", "done", "archived"),
    "project_visibility": ("public", "authenticated", "private"),
    "project_role": ("owner", "maintainer", "contributor", "viewer"),
    "project_invite_status": ("pending", "accepted", "declined", "revoked", "expired"),
    "project_link_kind": (
        "repository",
        "demo",
        "docs",
        "design",
        "video",
        "presentation",
        "other",
    ),
    "profile_block": ("about", "projects", "stats", "courses", "resume"),
}


def _enum(name: str) -> postgresql.ENUM:
    return postgresql.ENUM(*ENUMS[name], name=name, create_type=False)


def _audit_columns() -> tuple[sa.Column[Any], ...]:
    return (
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
        sa.Column("created_by", UUID, nullable=True),
        sa.Column("updated_by", UUID, nullable=True),
    )


def _audit_keys(table: str) -> tuple[sa.ForeignKeyConstraint, ...]:
    return (
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=f"fk_{table}_created_by_users", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"], ["users.id"], name=f"fk_{table}_updated_by_users", ondelete="SET NULL"
        ),
    )


def _project_key(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["project_id"],
        ["projects.id"],
        name=f"fk_{table}_project_id_projects",
        ondelete="CASCADE",
    )


def upgrade() -> None:
    bind = op.get_bind()
    for name, values in ENUMS.items():
        postgresql.ENUM(*values, name=name).create(bind)

    op.create_table(
        "projects",
        sa.Column("id", UUID, nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("summary", sa.String(length=280), nullable=True),
        sa.Column("readme_md", sa.Text(), server_default="", nullable=False),
        sa.Column("status", _enum("project_status"), server_default="idea", nullable=False),
        sa.Column(
            "visibility", _enum("project_visibility"), server_default="private", nullable=False
        ),
        sa.Column("logo_asset_id", UUID, nullable=True),
        sa.Column("status_changed_at", sa.DateTime(timezone=True), nullable=False),
        *_audit_columns(),
        sa.PrimaryKeyConstraint("id", name="pk_projects"),
        sa.UniqueConstraint("slug", name="uq_projects_slug"),
        sa.CheckConstraint("char_length(readme_md) <= 100000", name="ck_projects_readme_md_length"),
        sa.ForeignKeyConstraint(
            ["logo_asset_id"],
            ["assets.id"],
            name="fk_projects_logo_asset_id_assets",
            ondelete="SET NULL",
        ),
        *_audit_keys("projects"),
    )
    op.create_index("ix_projects_visibility_status", "projects", ["visibility", "status"])
    op.create_index("ix_projects_updated_at", "projects", ["updated_at"])
    op.create_index("ix_projects_status_changed_at", "projects", ["status_changed_at"])
    op.create_index("ix_projects_logo_asset_id", "projects", ["logo_asset_id"])

    op.create_table(
        "project_members",
        sa.Column("project_id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("role", _enum("project_role"), nullable=False),
        sa.Column("title", sa.String(length=80), nullable=True),
        sa.Column("show_in_profile", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("profile_position", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
        *_audit_columns(),
        sa.PrimaryKeyConstraint("project_id", "user_id", name="pk_project_members"),
        _project_key("project_members"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_project_members_user_id_users", ondelete="CASCADE"
        ),
        *_audit_keys("project_members"),
    )
    op.create_index(
        "uq_project_members_project_id_owner",
        "project_members",
        ["project_id"],
        unique=True,
        postgresql_where=sa.text("role = 'owner'"),
    )
    op.create_index("ix_project_members_user_id", "project_members", ["user_id"])

    op.create_table(
        "project_invites",
        sa.Column("id", UUID, nullable=False),
        sa.Column("project_id", UUID, nullable=False),
        sa.Column("invitee_id", UUID, nullable=False),
        sa.Column("inviter_id", UUID, nullable=True),
        sa.Column("role", _enum("project_role"), nullable=False),
        sa.Column("title", sa.String(length=80), nullable=True),
        sa.Column(
            "status", _enum("project_invite_status"), server_default="pending", nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        *_audit_columns(),
        sa.PrimaryKeyConstraint("id", name="pk_project_invites"),
        sa.CheckConstraint("role <> 'owner'", name="ck_project_invites_role_not_owner"),
        _project_key("project_invites"),
        sa.ForeignKeyConstraint(
            ["invitee_id"],
            ["users.id"],
            name="fk_project_invites_invitee_id_users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["inviter_id"],
            ["users.id"],
            name="fk_project_invites_inviter_id_users",
            ondelete="SET NULL",
        ),
        *_audit_keys("project_invites"),
    )
    op.create_index(
        "uq_project_invites_project_id_invitee_id_pending",
        "project_invites",
        ["project_id", "invitee_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index("ix_project_invites_invitee_id", "project_invites", ["invitee_id"])

    op.create_table(
        "project_links",
        sa.Column("id", UUID, nullable=False),
        sa.Column("project_id", UUID, nullable=False),
        sa.Column("kind", _enum("project_link_kind"), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=True),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        *_audit_columns(),
        sa.PrimaryKeyConstraint("id", name="pk_project_links"),
        _project_key("project_links"),
        *_audit_keys("project_links"),
    )
    op.create_index("ix_project_links_project_id_kind", "project_links", ["project_id", "kind"])

    op.create_table(
        "project_status_events",
        sa.Column("id", UUID, nullable=False),
        sa.Column("project_id", UUID, nullable=False),
        sa.Column("from_status", _enum("project_status"), nullable=True),
        sa.Column("to_status", _enum("project_status"), nullable=False),
        sa.Column("actor_id", UUID, nullable=True),
        *_audit_columns(),
        sa.PrimaryKeyConstraint("id", name="pk_project_status_events"),
        _project_key("project_status_events"),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
            name="fk_project_status_events_actor_id_users",
            ondelete="SET NULL",
        ),
        *_audit_keys("project_status_events"),
    )
    op.create_index("ix_project_status_events_project_id", "project_status_events", ["project_id"])

    op.create_table(
        "user_profile_blocks",
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("block", _enum("profile_block"), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("is_visible", sa.Boolean(), server_default="true", nullable=False),
        *_audit_columns(),
        sa.PrimaryKeyConstraint("user_id", "block", name="pk_user_profile_blocks"),
        sa.CheckConstraint("position >= 0", name="ck_user_profile_blocks_position_non_negative"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_user_profile_blocks_user_id_users",
            ondelete="CASCADE",
        ),
        *_audit_keys("user_profile_blocks"),
    )
    op.create_unique_constraint(
        "uq_user_profile_blocks_user_id_position",
        "user_profile_blocks",
        ["user_id", "position"],
        deferrable=True,
        initially="DEFERRED",
    )


def downgrade() -> None:
    op.drop_table("user_profile_blocks")
    op.drop_index("ix_project_status_events_project_id", table_name="project_status_events")
    op.drop_table("project_status_events")
    op.drop_index("ix_project_links_project_id_kind", table_name="project_links")
    op.drop_table("project_links")
    op.drop_index("ix_project_invites_invitee_id", table_name="project_invites")
    op.drop_index("uq_project_invites_project_id_invitee_id_pending", table_name="project_invites")
    op.drop_table("project_invites")
    op.drop_index("ix_project_members_user_id", table_name="project_members")
    op.drop_index("uq_project_members_project_id_owner", table_name="project_members")
    op.drop_table("project_members")
    op.drop_index("ix_projects_logo_asset_id", table_name="projects")
    op.drop_index("ix_projects_status_changed_at", table_name="projects")
    op.drop_index("ix_projects_updated_at", table_name="projects")
    op.drop_index("ix_projects_visibility_status", table_name="projects")
    op.drop_table("projects")

    bind = op.get_bind()
    for name in reversed(ENUMS):
        postgresql.ENUM(name=name).drop(bind)
