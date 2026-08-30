"""initial schema

Схема соответствует db.drawio: контент, производные interview_cards, тесты,
прогресс, пользователи и медиа. Перечисления — нативными типами Postgres.

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

asset_mime = postgresql.ENUM(
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/gif",
    "application/pdf",
    name="asset_mime",
    create_type=False,
)
content_status = postgresql.ENUM("draft", "published", name="content_status", create_type=False)
identity_provider = postgresql.ENUM("github", name="identity_provider", create_type=False)
question_type = postgresql.ENUM(
    "single",
    "multiple",
    "text",
    name="question_type",
    create_type=False,
)
user_role = postgresql.ENUM("student", "teacher", "admin", name="user_role", create_type=False)

ENUMS = (asset_mime, content_status, identity_provider, question_type, user_role)


def upgrade() -> None:
    bind = op.get_bind()
    for enum_type in ENUMS:
        enum_type.create(bind, checkfirst=False)

    op.create_table(
        "assets",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("s3_key", sa.String(length=512), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("mime", asset_mime, nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.CheckConstraint("size > 0", name=op.f("ck_assets_size_positive")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_assets")),
        sa.UniqueConstraint("s3_key", name=op.f("uq_assets_s3_key")),
    )
    op.create_table(
        "courses",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("color", sa.String(length=16), nullable=True),
        sa.Column("est_hours", sa.SmallInteger(), nullable=True),
        sa.Column("status", content_status, server_default="draft", nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_courses")),
        sa.UniqueConstraint("slug", name=op.f("uq_courses_slug")),
    )
    op.create_table(
        "student_groups",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("year", sa.SmallInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_student_groups")),
        sa.UniqueConstraint("name", "year", name="uq_student_groups_name_year"),
    )
    op.create_table(
        "tracks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("color", sa.String(length=16), nullable=True),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("status", content_status, server_default="draft", nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tracks")),
        sa.UniqueConstraint("slug", name=op.f("uq_tracks_slug")),
    )
    op.create_table(
        "modules",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("course_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("status", content_status, server_default="draft", nullable=False),
        sa.ForeignKeyConstraint(
            ["course_id"],
            ["courses.id"],
            name=op.f("fk_modules_course_id_courses"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_modules")),
        sa.UniqueConstraint("course_id", "slug", name="uq_modules_course_id_slug"),
        sa.UniqueConstraint(
            "course_id",
            "position",
            deferrable=True,
            initially="DEFERRED",
            name="uq_modules_course_id_position",
        ),
        sa.UniqueConstraint("id", "course_id", name="uq_modules_id_course_id"),
    )
    op.create_index("ix_modules_course_id", "modules", ["course_id"], unique=False)
    op.create_table(
        "tracks_course",
        sa.Column("track_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("course_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["course_id"],
            ["courses.id"],
            name=op.f("fk_tracks_course_course_id_courses"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["track_id"],
            ["tracks.id"],
            name=op.f("fk_tracks_course_track_id_tracks"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("track_id", "course_id", name=op.f("pk_tracks_course")),
        sa.UniqueConstraint(
            "track_id",
            "position",
            deferrable=True,
            initially="DEFERRED",
            name="uq_tracks_course_track_id_position",
        ),
    )
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("login", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("avatar_url", sa.String(length=512), nullable=True),
        sa.Column("student_number", sa.String(length=32), nullable=True),
        sa.Column("group_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=True),
        sa.Column("role", user_role, server_default="student", nullable=False),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["student_groups.id"],
            name=op.f("fk_users_group_id_student_groups"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
        sa.UniqueConstraint("login", name=op.f("uq_users_login")),
        sa.UniqueConstraint("student_number", name=op.f("uq_users_student_number")),
    )
    op.create_table(
        "lessons",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("module_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("est_minutes", sa.SmallInteger(), nullable=True),
        sa.Column("body_md", sa.Text(), nullable=False),
        sa.Column("body_html", sa.Text(), nullable=False),
        sa.Column("status", content_status, server_default="draft", nullable=False),
        sa.ForeignKeyConstraint(
            ["module_id"],
            ["modules.id"],
            name=op.f("fk_lessons_module_id_modules"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lessons")),
        sa.UniqueConstraint("module_id", "slug", name="uq_lessons_module_id_slug"),
        sa.UniqueConstraint(
            "module_id",
            "position",
            deferrable=True,
            initially="DEFERRED",
            name="uq_lessons_module_id_position",
        ),
        sa.UniqueConstraint("id", "module_id", name="uq_lessons_id_module_id"),
    )
    op.create_index("ix_lessons_module_id", "lessons", ["module_id"], unique=False)
    op.create_table(
        "module_deps",
        sa.Column("module_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("depends_on_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint("module_id <> depends_on_id", name=op.f("ck_module_deps_no_self_dep")),
        sa.ForeignKeyConstraint(
            ["depends_on_id"],
            ["modules.id"],
            name=op.f("fk_module_deps_depends_on_id_modules"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["module_id"],
            ["modules.id"],
            name=op.f("fk_module_deps_module_id_modules"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("module_id", "depends_on_id", name=op.f("pk_module_deps")),
    )
    op.create_table(
        "refresh_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("expired_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_refresh_tokens_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_refresh_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_refresh_tokens_token_hash")),
    )
    op.create_index("ix_refresh_tokens_expired_at", "refresh_tokens", ["expired_at"], unique=False)
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"], unique=False)
    op.create_table(
        "user_identities",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", identity_provider, nullable=False),
        sa.Column("provider_id", sa.String(length=128), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_user_identities_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_identities")),
        sa.UniqueConstraint(
            "provider",
            "provider_id",
            name="uq_user_identities_provider_provider_id",
        ),
        sa.UniqueConstraint("user_id", "provider", name="uq_user_identities_user_id_provider"),
    )
    op.create_index("ix_user_identities_user_id", "user_identities", ["user_id"], unique=False)
    op.create_table(
        "interview_cards",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lesson_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("question_md", sa.Text(), nullable=False),
        sa.Column("answer_md", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["lesson_id"],
            ["lessons.id"],
            name=op.f("fk_interview_cards_lesson_id_lessons"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_interview_cards")),
        sa.UniqueConstraint(
            "lesson_id",
            "position",
            deferrable=True,
            initially="DEFERRED",
            name="uq_interview_cards_lesson_id_position",
        ),
    )
    op.create_index("ix_interview_cards_lesson_id", "interview_cards", ["lesson_id"], unique=False)
    op.create_table(
        "lesson_progress",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lesson_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["lesson_id"],
            ["lessons.id"],
            name=op.f("fk_lesson_progress_lesson_id_lessons"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_lesson_progress_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "lesson_id", name=op.f("pk_lesson_progress")),
    )
    op.create_index("ix_lesson_progress_lesson_id", "lesson_progress", ["lesson_id"], unique=False)
    op.create_table(
        "quizzes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lesson_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("module_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("status", content_status, server_default="draft", nullable=False),
        sa.ForeignKeyConstraint(
            ["lesson_id", "module_id"],
            ["lessons.id", "lessons.module_id"],
            name="fk_quizzes_lesson_id_module_id_lessons",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["module_id"],
            ["modules.id"],
            name=op.f("fk_quizzes_module_id_modules"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_quizzes")),
        sa.UniqueConstraint("module_id", "slug", name="uq_quizzes_module_id_slug"),
        sa.UniqueConstraint(
            "module_id",
            "position",
            deferrable=True,
            initially="DEFERRED",
            name="uq_quizzes_module_id_position",
        ),
    )
    op.create_index("ix_quizzes_module_id", "quizzes", ["module_id"], unique=False)
    op.create_table(
        "quiz_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("quiz_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("max_score", sa.Integer(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("answers_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint("max_score > 0", name=op.f("ck_quiz_attempts_max_score_positive")),
        sa.CheckConstraint(
            "score >= 0 AND score <= max_score",
            name=op.f("ck_quiz_attempts_score_range"),
        ),
        sa.ForeignKeyConstraint(
            ["quiz_id"],
            ["quizzes.id"],
            name=op.f("fk_quiz_attempts_quiz_id_quizzes"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_quiz_attempts_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_quiz_attempts")),
    )
    op.create_index(
        "ix_quiz_attempts_user_id_quiz_id",
        "quiz_attempts",
        ["user_id", "quiz_id"],
        unique=False,
    )
    op.create_table(
        "quiz_questions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("quiz_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("prompt_md", sa.Text(), nullable=False),
        sa.Column("type", question_type, nullable=False),
        sa.Column("options_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("answer_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("explain_md", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["quiz_id"],
            ["quizzes.id"],
            name=op.f("fk_quiz_questions_quiz_id_quizzes"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_quiz_questions")),
        sa.UniqueConstraint(
            "quiz_id",
            "position",
            deferrable=True,
            initially="DEFERRED",
            name="uq_quiz_questions_quiz_id_position",
        ),
    )
    op.create_index("ix_quiz_questions_quiz_id", "quiz_questions", ["quiz_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_quiz_questions_quiz_id", table_name="quiz_questions")
    op.drop_table("quiz_questions")
    op.drop_index("ix_quiz_attempts_user_id_quiz_id", table_name="quiz_attempts")
    op.drop_table("quiz_attempts")
    op.drop_index("ix_quizzes_module_id", table_name="quizzes")
    op.drop_table("quizzes")
    op.drop_index("ix_lesson_progress_lesson_id", table_name="lesson_progress")
    op.drop_table("lesson_progress")
    op.drop_index("ix_interview_cards_lesson_id", table_name="interview_cards")
    op.drop_table("interview_cards")
    op.drop_index("ix_user_identities_user_id", table_name="user_identities")
    op.drop_table("user_identities")
    op.drop_index("ix_refresh_tokens_user_id", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_expired_at", table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
    op.drop_table("module_deps")
    op.drop_index("ix_lessons_module_id", table_name="lessons")
    op.drop_table("lessons")
    op.drop_table("users")
    op.drop_table("tracks_course")
    op.drop_index("ix_modules_course_id", table_name="modules")
    op.drop_table("modules")
    op.drop_table("tracks")
    op.drop_table("student_groups")
    op.drop_table("courses")
    op.drop_table("assets")

    bind = op.get_bind()
    for enum_type in ENUMS:
        enum_type.drop(bind, checkfirst=False)
