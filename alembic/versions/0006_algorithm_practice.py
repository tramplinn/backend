"""algorithm practice domain and module items

Revision ID: 0006_algorithm_practice
Revises: 0005_quiz_interactions
Create Date: 2026-09-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_algorithm_practice"
down_revision: str | None = "0005_quiz_interactions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
AUDIT = (
    sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    ),
    sa.Column(
        "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    ),
    sa.Column("created_by", UUID, nullable=True),
    sa.Column("updated_by", UUID, nullable=True),
)


def _enum(name: str, *values: str) -> postgresql.ENUM:
    return postgresql.ENUM(*values, name=name, create_type=False)


def _audit_fks(table: str) -> tuple[sa.ForeignKeyConstraint, sa.ForeignKeyConstraint]:
    return (
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=f"fk_{table}_created_by_users", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"], ["users.id"], name=f"fk_{table}_updated_by_users", ondelete="SET NULL"
        ),
    )


def upgrade() -> None:
    enums = {
        "algorithm_provider": ("internal", "leetcode", "codeforces", "external"),
        "algorithm_difficulty": ("easy", "medium", "hard"),
        "practice_mode": ("practice", "mock_interview"),
        "practice_session_status": ("active", "completed", "expired"),
        "submission_kind": ("run", "submit"),
        "submission_status": ("queued", "running", "finished", "failed"),
        "algorithm_verdict": (
            "accepted",
            "wrong_answer",
            "compile_error",
            "runtime_error",
            "time_limit",
            "memory_limit",
            "output_limit",
            "internal_error",
        ),
        "algorithm_progress_status": ("unseen", "attempted", "solved", "review"),
    }
    for name, values in enums.items():
        postgresql.ENUM(*values, name=name).create(op.get_bind())

    op.create_table(
        "algorithm_problems",
        sa.Column("id", UUID, nullable=False),
        sa.Column(
            "provider", _enum("algorithm_provider", *enums["algorithm_provider"]), nullable=False
        ),
        sa.Column("external_key", sa.String(200)),
        sa.Column("external_url", sa.String(2048)),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("statement_md", sa.Text(), nullable=False),
        sa.Column("statement_html", sa.Text(), nullable=False),
        sa.Column(
            "difficulty",
            _enum("algorithm_difficulty", *enums["algorithm_difficulty"]),
            nullable=False,
        ),
        sa.Column("topics", postgresql.ARRAY(sa.String(64)), nullable=False),
        sa.Column("time_limit_ms", sa.Integer(), nullable=False),
        sa.Column("memory_limit_kb", sa.Integer(), nullable=False),
        sa.Column("status", _enum("content_status", "draft", "published"), nullable=False),
        *AUDIT,
        sa.PrimaryKeyConstraint("id", name="pk_algorithm_problems"),
        *_audit_fks("algorithm_problems"),
        sa.CheckConstraint(
            "time_limit_ms BETWEEN 50 AND 5000", name="ck_algorithm_problems_algorithm_problem_time"
        ),
        sa.CheckConstraint(
            "memory_limit_kb BETWEEN 16384 AND 524288",
            name="ck_algorithm_problems_algorithm_problem_memory",
        ),
        sa.CheckConstraint(
            "provider = 'internal' OR external_url IS NOT NULL",
            name="ck_algorithm_problems_algorithm_problem_external_url",
        ),
    )
    op.create_table(
        "algorithm_test_cases",
        sa.Column("id", UUID, nullable=False),
        sa.Column("problem_id", UUID, nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("input", sa.Text(), nullable=False),
        sa.Column("expected_output", sa.Text(), nullable=False),
        sa.Column("is_sample", sa.Boolean(), nullable=False),
        sa.Column("weight", sa.SmallInteger(), nullable=False),
        *AUDIT,
        sa.PrimaryKeyConstraint("id", name="pk_algorithm_test_cases"),
        sa.ForeignKeyConstraint(
            ["problem_id"],
            ["algorithm_problems.id"],
            name="fk_algorithm_test_cases_problem_id_algorithm_problems",
            ondelete="CASCADE",
        ),
        *_audit_fks("algorithm_test_cases"),
        sa.CheckConstraint("weight > 0", name="ck_algorithm_test_cases_algorithm_test_case_weight"),
        sa.UniqueConstraint(
            "problem_id",
            "position",
            name="uq_algorithm_test_cases_problem_id_position",
            deferrable=True,
            initially="DEFERRED",
        ),
    )
    op.create_index("ix_algorithm_test_cases_problem_id", "algorithm_test_cases", ["problem_id"])
    op.create_table(
        "algorithm_templates",
        sa.Column("problem_id", UUID, nullable=False),
        sa.Column("language", sa.String(32), nullable=False),
        sa.Column("starter_code", sa.Text(), nullable=False),
        sa.Column("solution_code", sa.Text(), nullable=False),
        sa.Column("validated_at", sa.DateTime(timezone=True)),
        *AUDIT,
        sa.PrimaryKeyConstraint("problem_id", "language", name="pk_algorithm_templates"),
        sa.ForeignKeyConstraint(
            ["problem_id"],
            ["algorithm_problems.id"],
            name="fk_algorithm_templates_problem_id_algorithm_problems",
            ondelete="CASCADE",
        ),
        *_audit_fks("algorithm_templates"),
    )
    op.create_table(
        "practice_sets",
        sa.Column("id", UUID, nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("mode", _enum("practice_mode", *enums["practice_mode"]), nullable=False),
        sa.Column("duration_minutes", sa.SmallInteger()),
        sa.Column("status", _enum("content_status", "draft", "published"), nullable=False),
        *AUDIT,
        sa.PrimaryKeyConstraint("id", name="pk_practice_sets"),
        *_audit_fks("practice_sets"),
    )
    op.create_table(
        "practice_set_problems",
        sa.Column("practice_set_id", UUID, nullable=False),
        sa.Column("problem_id", UUID, nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("recommended_minutes", sa.SmallInteger()),
        *AUDIT,
        sa.PrimaryKeyConstraint("practice_set_id", "problem_id", name="pk_practice_set_problems"),
        sa.ForeignKeyConstraint(
            ["practice_set_id"],
            ["practice_sets.id"],
            name="fk_practice_set_problems_practice_set_id_practice_sets",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["problem_id"],
            ["algorithm_problems.id"],
            name="fk_practice_set_problems_problem_id_algorithm_problems",
            ondelete="CASCADE",
        ),
        *_audit_fks("practice_set_problems"),
        sa.UniqueConstraint(
            "practice_set_id",
            "position",
            name="uq_practice_set_problems_practice_set_id_position",
            deferrable=True,
            initially="DEFERRED",
        ),
    )
    op.create_table(
        "practice_sessions",
        sa.Column("id", UUID, nullable=False),
        sa.Column("practice_set_id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("mode", _enum("practice_mode", *enums["practice_mode"]), nullable=False),
        sa.Column(
            "status",
            _enum("practice_session_status", *enums["practice_session_status"]),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deadline_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("reflection_md", sa.Text()),
        *AUDIT,
        sa.PrimaryKeyConstraint("id", name="pk_practice_sessions"),
        sa.ForeignKeyConstraint(
            ["practice_set_id"],
            ["practice_sets.id"],
            name="fk_practice_sessions_practice_set_id_practice_sets",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_practice_sessions_user_id_users", ondelete="CASCADE"
        ),
        *_audit_fks("practice_sessions"),
    )
    op.create_index("ix_practice_sessions_user_id", "practice_sessions", ["user_id"])
    op.create_table(
        "algorithm_submissions",
        sa.Column("id", UUID, nullable=False),
        sa.Column("session_id", UUID, nullable=False),
        sa.Column("problem_id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("kind", _enum("submission_kind", *enums["submission_kind"]), nullable=False),
        sa.Column("language", sa.String(32), nullable=False),
        sa.Column("source_code", sa.Text(), nullable=False),
        sa.Column("custom_input", sa.Text()),
        sa.Column(
            "status", _enum("submission_status", *enums["submission_status"]), nullable=False
        ),
        sa.Column("verdict", _enum("algorithm_verdict", *enums["algorithm_verdict"])),
        sa.Column("runtime_ms", sa.Integer()),
        sa.Column("memory_kb", sa.Integer()),
        sa.Column("failed_test", sa.Integer()),
        sa.Column("stdout", sa.Text()),
        sa.Column("stderr", sa.Text()),
        sa.Column("safe_error", sa.Text()),
        sa.Column("judge_token", sa.LargeBinary()),
        sa.Column("result_json", postgresql.JSONB()),
        sa.Column("progress_counted", sa.Boolean(), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        *AUDIT,
        sa.PrimaryKeyConstraint("id", name="pk_algorithm_submissions"),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["practice_sessions.id"],
            name="fk_algorithm_submissions_session_id_practice_sessions",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["problem_id"],
            ["algorithm_problems.id"],
            name="fk_algorithm_submissions_problem_id_algorithm_problems",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_algorithm_submissions_user_id_users",
            ondelete="CASCADE",
        ),
        *_audit_fks("algorithm_submissions"),
        sa.CheckConstraint(
            "kind = 'run' OR custom_input IS NULL",
            name="ck_algorithm_submissions_algorithm_submission_submit_no_input",
        ),
    )
    op.create_index(
        "ix_algorithm_submissions_queue", "algorithm_submissions", ["status", "created_at"]
    )
    op.create_index("ix_algorithm_submissions_user_id", "algorithm_submissions", ["user_id"])
    op.create_table(
        "algorithm_progress",
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("problem_id", UUID, nullable=False),
        sa.Column(
            "status",
            _enum("algorithm_progress_status", *enums["algorithm_progress_status"]),
            nullable=False,
        ),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("hints_used", sa.Integer(), nullable=False),
        sa.Column("first_solved_at", sa.DateTime(timezone=True)),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("confidence", sa.SmallInteger()),
        sa.Column("complexity_md", sa.Text()),
        sa.Column("reflection_md", sa.Text()),
        sa.Column("last_counted_submission_id", UUID),
        *AUDIT,
        sa.PrimaryKeyConstraint("user_id", "problem_id", name="pk_algorithm_progress"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_algorithm_progress_user_id_users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["problem_id"],
            ["algorithm_problems.id"],
            name="fk_algorithm_progress_problem_id_algorithm_problems",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["last_counted_submission_id"],
            ["algorithm_submissions.id"],
            name="fk_algorithm_progress_last_submission",
            ondelete="SET NULL",
        ),
        *_audit_fks("algorithm_progress"),
    )
    op.create_table(
        "algorithm_job_outbox",
        sa.Column("submission_id", UUID, nullable=False),
        sa.Column("dispatched_at", sa.DateTime(timezone=True)),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text()),
        *AUDIT,
        sa.PrimaryKeyConstraint("submission_id", name="pk_algorithm_job_outbox"),
        sa.ForeignKeyConstraint(
            ["submission_id"],
            ["algorithm_submissions.id"],
            name="fk_algorithm_job_outbox_submission_id_algorithm_submissions",
            ondelete="CASCADE",
        ),
        *_audit_fks("algorithm_job_outbox"),
    )

    op.add_column("module_items", sa.Column("practice_set_id", UUID, nullable=True))
    op.create_foreign_key(
        "fk_module_items_practice_set_id_practice_sets",
        "module_items",
        "practice_sets",
        ["practice_set_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint(
        "uq_module_items_practice_set_id", "module_items", ["practice_set_id"]
    )
    op.drop_constraint("ck_module_items_module_items_one_target", "module_items", type_="check")
    op.create_check_constraint(
        "module_items_one_target",
        "module_items",
        "num_nonnulls(lesson_id, quiz_id, practice_set_id) = 1",
    )


def downgrade() -> None:
    op.drop_constraint("ck_module_items_module_items_one_target", "module_items", type_="check")
    op.create_check_constraint(
        "module_items_one_target", "module_items", "num_nonnulls(lesson_id, quiz_id) = 1"
    )
    op.drop_constraint("uq_module_items_practice_set_id", "module_items", type_="unique")
    op.drop_constraint(
        "fk_module_items_practice_set_id_practice_sets", "module_items", type_="foreignkey"
    )
    op.drop_column("module_items", "practice_set_id")
    for table in (
        "algorithm_job_outbox",
        "algorithm_progress",
        "algorithm_submissions",
        "practice_sessions",
        "practice_set_problems",
        "practice_sets",
        "algorithm_templates",
        "algorithm_test_cases",
        "algorithm_problems",
    ):
        op.drop_table(table)
    for name in (
        "algorithm_progress_status",
        "algorithm_verdict",
        "submission_status",
        "submission_kind",
        "practice_session_status",
        "practice_mode",
        "algorithm_difficulty",
        "algorithm_provider",
    ):
        postgresql.ENUM(name=name).drop(op.get_bind())
