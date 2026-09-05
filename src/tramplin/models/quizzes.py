from typing import TYPE_CHECKING, Any

import uuid_utils.compat as uuid
from sqlalchemy import (
    Column,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from tramplin.models.base import Base, SoftDeleteMixin, UUIDPrimaryKey
from tramplin.models.content import Lesson, Module, position_unique, status_column
from tramplin.models.enums import ContentStatus, QuestionType

if TYPE_CHECKING:
    from tramplin.models.assets import Asset


quiz_question_assets = Table(
    "quiz_question_assets",
    Base.metadata,
    Column(
        "question_id",
        ForeignKey("quiz_questions.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("asset_id", ForeignKey("assets.id", ondelete="CASCADE"), primary_key=True),
)


class Quiz(UUIDPrimaryKey, SoftDeleteMixin):
    """Тест модуля (lesson_id IS NULL) либо конкретного урока внутри этого модуля."""

    __tablename__ = "quizzes"
    __table_args__ = (
        ForeignKeyConstraint(
            ["lesson_id", "module_id"],
            ["lessons.id", "lessons.module_id"],
            name="fk_quizzes_lesson_id_module_id_lessons",
            ondelete="CASCADE",
        ),
        Index(
            "uq_quizzes_module_id_slug",
            "module_id",
            "slug",
            unique=True,
            postgresql_where=text("NOT is_deleted"),
        ),
        UniqueConstraint("id", "module_id", name="uq_quizzes_id_module_id"),
    )

    lesson_id: Mapped[uuid.UUID | None] = mapped_column()
    module_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("modules.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(120))
    status: Mapped[ContentStatus] = status_column()

    module: Mapped[Module] = relationship(back_populates="quizzes", foreign_keys=[module_id])
    lesson: Mapped[Lesson | None] = relationship(
        primaryjoin="Quiz.lesson_id == Lesson.id",
        foreign_keys=[lesson_id],
        viewonly=True,
    )
    questions: Mapped[list[QuizQuestion]] = relationship(
        back_populates="quiz",
        cascade="all, delete-orphan",
        order_by="QuizQuestion.position",
    )


class QuizQuestion(UUIDPrimaryKey):
    """answer_json не покидает сервер до отправки ответов: выбираем явным списком колонок."""

    __tablename__ = "quiz_questions"
    __table_args__ = (position_unique("quiz_questions", "quiz_id"),)

    quiz_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("quizzes.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer(), default=0)
    prompt_md: Mapped[str] = mapped_column(Text())
    type: Mapped[QuestionType] = mapped_column(default=QuestionType.SINGLE)
    options_json: Mapped[list[Any]] = mapped_column(default=list)
    answer_json: Mapped[dict[str, Any]] = mapped_column(default=dict)
    explain_md: Mapped[str | None] = mapped_column(Text())

    quiz: Mapped[Quiz] = relationship(back_populates="questions")
    attachments: Mapped[list[Asset]] = relationship(secondary=quiz_question_assets)


Index("ix_quizzes_module_id", Quiz.module_id)
Index("ix_quiz_questions_quiz_id", QuizQuestion.quiz_id)
