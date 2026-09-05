"""recommendation embeddings

Revision ID: 0015_recommendation_embeddings
Revises: ef6496bf6cb9
Create Date: 2026-09-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0015_recommendation_embeddings"
down_revision: str | None = "ef6496bf6cb9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBEDDING_DIM = 512


def _enum(name: str, *values: str) -> postgresql.ENUM:
    return postgresql.ENUM(*values, name=name, create_type=False)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    postgresql.ENUM(
        "course",
        "algorithm_problem",
        name="recommendation_entity_type",
    ).create(op.get_bind())

    op.add_column(
        "courses",
        sa.Column(
            "topics",
            postgresql.ARRAY(sa.String(64)),
            nullable=False,
            server_default="{}",
        ),
    )
    op.add_column("courses", sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True))
    op.add_column(
        "algorithm_problems",
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True),
    )

    op.create_table(
        "embedding_job_outbox",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "entity_type",
            _enum("recommendation_entity_type", "course", "algorithm_problem"),
            nullable=False,
        ),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "updated_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.UniqueConstraint("entity_type", "entity_id", name="uq_embedding_job_outbox_entity"),
    )


def downgrade() -> None:
    op.drop_table("embedding_job_outbox")
    op.drop_column("algorithm_problems", "embedding")
    op.drop_column("courses", "embedding")
    op.drop_column("courses", "topics")
    postgresql.ENUM(name="recommendation_entity_type").drop(op.get_bind())
    op.execute("DROP EXTENSION IF EXISTS vector")
