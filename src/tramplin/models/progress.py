from datetime import datetime
from typing import Any

import uuid_utils.compat as uuid
from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from tramplin.models.base import Base, UUIDPrimaryKey
from tramplin.models.content import Lesson
from tramplin.models.quizzes import Quiz
from tramplin.models.users import User


class LessonProgress(Base):
    __tablename__ = "lesson_progress"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    lesson_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("lessons.id", ondelete="CASCADE"),
        primary_key=True,
    )
    completed_at: Mapped[datetime] = mapped_column(server_default=func.now())

    user: Mapped[User] = relationship(foreign_keys=[user_id])
    lesson: Mapped[Lesson] = relationship()


class QuizAttempt(UUIDPrimaryKey, Base):
    """Итог проверки на сервере: клиент присылает answers_json, score считает бэкенд."""

    __tablename__ = "quiz_attempts"
    __table_args__ = (
        CheckConstraint("score >= 0 AND score <= max_score", name="score_range"),
        CheckConstraint("max_score > 0", name="max_score_positive"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    quiz_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("quizzes.id", ondelete="CASCADE"))
    max_score: Mapped[int] = mapped_column(Integer())
    score: Mapped[int] = mapped_column(Integer(), default=0)
    answers_json: Mapped[dict[str, Any]] = mapped_column(default=dict)

    user: Mapped[User] = relationship(foreign_keys=[user_id])
    quiz: Mapped[Quiz] = relationship()


Index("ix_lesson_progress_lesson_id", LessonProgress.lesson_id)
Index("ix_quiz_attempts_user_id_quiz_id", QuizAttempt.user_id, QuizAttempt.quiz_id)
