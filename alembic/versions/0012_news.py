"""news for the home page

Revision ID: 0012_news
Revises: 0011_free_practice_sessions
Create Date: 2026-09-03
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012_news"
down_revision: str | None = "0011_free_practice_sessions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
content_status = postgresql.ENUM("draft", "published", name="content_status", create_type=False)


def _audit_columns() -> tuple[sa.Column[Any], ...]:
    """Те же четыре колонки аудита, что Base подмешивает в каждую таблицу."""
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


def upgrade() -> None:
    op.create_table(
        "news",
        sa.Column("id", UUID, nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("body_md", sa.Text(), nullable=False),
        sa.Column("status", content_status, server_default="draft", nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        *_audit_columns(),
        sa.PrimaryKeyConstraint("id", name="pk_news"),
        sa.UniqueConstraint("slug", name="uq_news_slug"),
        *_audit_keys("news"),
    )
    # Лента отдаётся по убыванию даты публикации, индекс повторяет этот порядок.
    op.create_index("ix_news_published_at", "news", [sa.text("published_at DESC")])

    op.create_table(
        "news_photos",
        sa.Column("news_id", UUID, nullable=False),
        sa.Column("asset_id", UUID, nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        *_audit_columns(),
        sa.PrimaryKeyConstraint("news_id", "asset_id", name="pk_news_photos"),
        sa.ForeignKeyConstraint(
            ["news_id"], ["news.id"], name="fk_news_photos_news_id_news", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["asset_id"], ["assets.id"], name="fk_news_photos_asset_id_assets", ondelete="CASCADE"
        ),
        *_audit_keys("news_photos"),
    )
    # Отложенная проверка: перестановка фото укладывается в одну транзакцию.
    op.create_unique_constraint(
        "uq_news_photos_news_id_position",
        "news_photos",
        ["news_id", "position"],
        deferrable=True,
        initially="DEFERRED",
    )


def downgrade() -> None:
    op.drop_table("news_photos")
    op.drop_index("ix_news_published_at", table_name="news")
    op.drop_table("news")
