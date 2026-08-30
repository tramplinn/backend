"""interactive quiz questions and file attachments

Revision ID: 0005_quiz_interactions
Revises: 0004_module_items
Create Date: 2026-08-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_quiz_interactions"
down_revision: str | None = "0004_module_items"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE question_type ADD VALUE IF NOT EXISTS 'matching'")
    op.execute("ALTER TYPE question_type ADD VALUE IF NOT EXISTS 'grouping'")
    op.execute("ALTER TYPE question_type ADD VALUE IF NOT EXISTS 'file'")
    op.create_table(
        "quiz_question_assets",
        sa.Column("question_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["question_id"],
            ["quiz_questions.id"],
            name="fk_quiz_question_assets_question_id_quiz_questions",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["assets.id"],
            name="fk_quiz_question_assets_asset_id_assets",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "question_id",
            "asset_id",
            name="pk_quiz_question_assets",
        ),
    )


def downgrade() -> None:
    op.drop_table("quiz_question_assets")
    op.execute(
        "UPDATE quiz_questions SET type = 'text' WHERE type IN ('matching', 'grouping', 'file')"
    )
    op.execute("ALTER TYPE question_type RENAME TO question_type_old")
    replacement = postgresql.ENUM(
        "single",
        "multiple",
        "text",
        name="question_type",
        create_type=False,
    )
    replacement.create(op.get_bind(), checkfirst=False)
    op.execute(
        "ALTER TABLE quiz_questions ALTER COLUMN type TYPE question_type "
        "USING type::text::question_type"
    )
    op.execute("DROP TYPE question_type_old")
