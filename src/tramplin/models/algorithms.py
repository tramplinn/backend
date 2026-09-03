from datetime import datetime

import uuid_utils.compat as uuid
from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    SmallInteger,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from tramplin.models.base import Base, UUIDPrimaryKey
from tramplin.models.content import position_unique, status_column
from tramplin.models.enums import (
    AlgorithmDifficulty,
    AlgorithmProgressStatus,
    AlgorithmProvider,
    AlgorithmVerdict,
    ContentStatus,
    PracticeMode,
    PracticeSessionStatus,
    SubmissionKind,
    SubmissionStatus,
)


class AlgorithmProblem(UUIDPrimaryKey):
    __tablename__ = "algorithm_problems"
    __table_args__ = (
        CheckConstraint("time_limit_ms BETWEEN 50 AND 5000", name="algorithm_problem_time"),
        CheckConstraint(
            "memory_limit_kb BETWEEN 16384 AND 524288", name="algorithm_problem_memory"
        ),
        CheckConstraint(
            "provider = 'internal' OR external_url IS NOT NULL",
            name="algorithm_problem_external_url",
        ),
    )

    provider: Mapped[AlgorithmProvider] = mapped_column(default=AlgorithmProvider.INTERNAL)
    external_key: Mapped[str | None] = mapped_column(String(200))
    external_url: Mapped[str | None] = mapped_column(String(2048))
    title: Mapped[str] = mapped_column(String(200))
    statement_md: Mapped[str] = mapped_column(Text(), default="")
    statement_html: Mapped[str] = mapped_column(Text(), default="")
    difficulty: Mapped[AlgorithmDifficulty]
    topics: Mapped[list[str]] = mapped_column(ARRAY(String(64)), default=list)
    time_limit_ms: Mapped[int] = mapped_column(Integer(), default=1000)
    memory_limit_kb: Mapped[int] = mapped_column(Integer(), default=262144)
    status: Mapped[ContentStatus] = status_column()

    test_cases: Mapped[list[AlgorithmTestCase]] = relationship(
        back_populates="problem",
        cascade="all, delete-orphan",
        order_by="AlgorithmTestCase.position",
    )
    templates: Mapped[list[AlgorithmTemplate]] = relationship(
        back_populates="problem",
        cascade="all, delete-orphan",
        order_by="AlgorithmTemplate.language",
    )


class AlgorithmTestCase(UUIDPrimaryKey):
    __tablename__ = "algorithm_test_cases"
    __table_args__ = (
        position_unique("algorithm_test_cases", "problem_id"),
        CheckConstraint("weight > 0", name="algorithm_test_case_weight"),
    )

    problem_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("algorithm_problems.id", ondelete="CASCADE")
    )
    position: Mapped[int] = mapped_column(Integer())
    input: Mapped[str] = mapped_column(Text(), default="")
    expected_output: Mapped[str] = mapped_column(Text())
    is_sample: Mapped[bool] = mapped_column(default=False)
    weight: Mapped[int] = mapped_column(SmallInteger(), default=1)

    problem: Mapped[AlgorithmProblem] = relationship(back_populates="test_cases")


class AlgorithmTemplate(Base):
    __tablename__ = "algorithm_templates"

    problem_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("algorithm_problems.id", ondelete="CASCADE"), primary_key=True
    )
    language: Mapped[str] = mapped_column(String(32), primary_key=True)
    starter_code: Mapped[str] = mapped_column(Text(), default="")
    solution_code: Mapped[str] = mapped_column(Text(), default="")
    validated_at: Mapped[datetime | None]

    problem: Mapped[AlgorithmProblem] = relationship(back_populates="templates")


class PracticeSet(UUIDPrimaryKey):
    __tablename__ = "practice_sets"

    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text(), default="")
    mode: Mapped[PracticeMode] = mapped_column(default=PracticeMode.PRACTICE)
    duration_minutes: Mapped[int | None] = mapped_column(SmallInteger())
    status: Mapped[ContentStatus] = status_column()

    problems: Mapped[list[PracticeSetProblem]] = relationship(
        back_populates="practice_set",
        cascade="all, delete-orphan",
        order_by="PracticeSetProblem.position",
    )


class PracticeSetProblem(Base):
    __tablename__ = "practice_set_problems"
    __table_args__ = (position_unique("practice_set_problems", "practice_set_id"),)

    practice_set_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("practice_sets.id", ondelete="CASCADE"), primary_key=True
    )
    problem_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("algorithm_problems.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer())
    recommended_minutes: Mapped[int | None] = mapped_column(SmallInteger())

    practice_set: Mapped[PracticeSet] = relationship(back_populates="problems")
    problem: Mapped[AlgorithmProblem] = relationship()


class PracticeSession(UUIDPrimaryKey):
    __tablename__ = "practice_sessions"

    # NULL — свободная сессия тренажёра: задача решается вне набора практики.
    practice_set_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("practice_sets.id", ondelete="RESTRICT")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    mode: Mapped[PracticeMode]
    status: Mapped[PracticeSessionStatus] = mapped_column(default=PracticeSessionStatus.ACTIVE)
    started_at: Mapped[datetime]
    deadline_at: Mapped[datetime | None]
    completed_at: Mapped[datetime | None]
    reflection_md: Mapped[str | None] = mapped_column(Text())

    practice_set: Mapped[PracticeSet | None] = relationship()


class AlgorithmSubmission(UUIDPrimaryKey):
    __tablename__ = "algorithm_submissions"
    __table_args__ = (
        CheckConstraint(
            "kind = 'run' OR custom_input IS NULL", name="algorithm_submission_submit_no_input"
        ),
    )

    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("practice_sessions.id", ondelete="CASCADE")
    )
    problem_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("algorithm_problems.id", ondelete="RESTRICT")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[SubmissionKind]
    language: Mapped[str] = mapped_column(String(32))
    source_code: Mapped[str] = mapped_column(Text())
    custom_input: Mapped[str | None] = mapped_column(Text())
    status: Mapped[SubmissionStatus] = mapped_column(default=SubmissionStatus.QUEUED)
    verdict: Mapped[AlgorithmVerdict | None]
    runtime_ms: Mapped[int | None]
    memory_kb: Mapped[int | None]
    failed_test: Mapped[int | None]
    stdout: Mapped[str | None] = mapped_column(Text())
    stderr: Mapped[str | None] = mapped_column(Text())
    safe_error: Mapped[str | None] = mapped_column(Text())
    judge_token: Mapped[bytes | None] = mapped_column(LargeBinary())
    result_json: Mapped[dict[str, object] | None] = mapped_column(JSONB())
    progress_counted: Mapped[bool] = mapped_column(default=False)
    claimed_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]


class AlgorithmProgress(Base):
    __tablename__ = "algorithm_progress"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    problem_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("algorithm_problems.id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[AlgorithmProgressStatus] = mapped_column(default=AlgorithmProgressStatus.UNSEEN)
    attempts: Mapped[int] = mapped_column(Integer(), default=0)
    hints_used: Mapped[int] = mapped_column(Integer(), default=0)
    first_solved_at: Mapped[datetime | None]
    last_attempt_at: Mapped[datetime | None]
    confidence: Mapped[int | None] = mapped_column(SmallInteger())
    complexity_md: Mapped[str | None] = mapped_column(Text())
    reflection_md: Mapped[str | None] = mapped_column(Text())
    last_counted_submission_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "algorithm_submissions.id",
            name="fk_algorithm_progress_last_submission",
            ondelete="SET NULL",
        )
    )


class AlgorithmJobOutbox(Base):
    """Transactional outbox: one durable queue event for every submission."""

    __tablename__ = "algorithm_job_outbox"

    submission_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("algorithm_submissions.id", ondelete="CASCADE"), primary_key=True
    )
    dispatched_at: Mapped[datetime | None]
    attempts: Mapped[int] = mapped_column(Integer(), default=0)
    last_error: Mapped[str | None] = mapped_column(Text())


Index("ix_algorithm_problems_status", AlgorithmProblem.status)
Index("ix_algorithm_test_cases_problem_id", AlgorithmTestCase.problem_id)
Index("ix_practice_sessions_user_id", PracticeSession.user_id)
Index("ix_algorithm_submissions_queue", AlgorithmSubmission.status, AlgorithmSubmission.created_at)
Index("ix_algorithm_submissions_user_id", AlgorithmSubmission.user_id)
