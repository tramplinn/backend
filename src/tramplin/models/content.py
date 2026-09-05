from typing import TYPE_CHECKING

import uuid_utils.compat as uuid
from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    SmallInteger,
    String,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from tramplin.models.base import Base, SoftDeleteMixin, UUIDPrimaryKey
from tramplin.models.enums import ContentStatus
from tramplin.models.recommendations import EMBEDDING_DIM
from tramplin.models.tags import Tag

if TYPE_CHECKING:
    from tramplin.models.algorithms import PracticeSet
    from tramplin.models.assets import Asset
    from tramplin.models.quizzes import Quiz

course_tags = Table(
    "course_tags",
    Base.metadata,
    Column("course_id", ForeignKey("courses.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)


def status_column() -> Mapped[ContentStatus]:
    return mapped_column(default=ContentStatus.DRAFT, server_default=ContentStatus.DRAFT.value)


def position_unique(table: str, parent: str) -> UniqueConstraint:
    """Отложенная проверка: перестановка соседей укладывается в одну транзакцию."""
    return UniqueConstraint(
        parent,
        "position",
        name=f"uq_{table}_{parent}_position",
        deferrable=True,
        initially="DEFERRED",
    )


class Track(UUIDPrimaryKey, SoftDeleteMixin):
    __tablename__ = "tracks"
    __table_args__ = (
        Index("uq_tracks_slug", "slug", unique=True, postgresql_where=text("NOT is_deleted")),
    )

    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text())
    color: Mapped[str | None] = mapped_column(String(16))
    slug: Mapped[str] = mapped_column(String(120))
    status: Mapped[ContentStatus] = status_column()

    courses: Mapped[list[TrackCourse]] = relationship(
        back_populates="track",
        cascade="all, delete-orphan",
        order_by="TrackCourse.position",
    )


class Course(UUIDPrimaryKey, SoftDeleteMixin):
    __tablename__ = "courses"
    __table_args__ = (
        Index("uq_courses_slug", "slug", unique=True, postgresql_where=text("NOT is_deleted")),
    )

    title: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str | None] = mapped_column(Text())
    slug: Mapped[str] = mapped_column(String(120))
    color: Mapped[str | None] = mapped_column(String(16))
    est_hours: Mapped[int | None] = mapped_column(SmallInteger())
    cover_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"),
        index=True,
    )
    status: Mapped[ContentStatus] = status_column()
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))

    cover_asset: Mapped[Asset | None] = relationship()
    tags: Mapped[list[Tag]] = relationship(secondary=course_tags, order_by="Tag.name")
    modules: Mapped[list[Module]] = relationship(
        back_populates="course",
        cascade="all, delete-orphan",
        order_by="Module.position",
    )
    tracks: Mapped[list[TrackCourse]] = relationship(
        back_populates="course",
        cascade="all, delete-orphan",
    )


class TrackCourse(Base):
    __tablename__ = "tracks_course"
    __table_args__ = (position_unique("tracks_course", "track_id"),)

    track_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tracks.id", ondelete="CASCADE"),
        primary_key=True,
    )
    course_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"),
        primary_key=True,
    )
    position: Mapped[int] = mapped_column(Integer(), default=0)

    track: Mapped[Track] = relationship(back_populates="courses")
    course: Mapped[Course] = relationship(back_populates="tracks")


class Module(UUIDPrimaryKey, SoftDeleteMixin):
    __tablename__ = "modules"
    __table_args__ = (
        Index(
            "uq_modules_course_id_slug",
            "course_id",
            "slug",
            unique=True,
            postgresql_where=text("NOT is_deleted"),
        ),
        position_unique("modules", "course_id"),
        UniqueConstraint("id", "course_id", name="uq_modules_id_course_id"),
    )

    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str | None] = mapped_column(Text())
    slug: Mapped[str] = mapped_column(String(120))
    position: Mapped[int] = mapped_column(Integer(), default=0)
    status: Mapped[ContentStatus] = status_column()

    course: Mapped[Course] = relationship(back_populates="modules")
    items: Mapped[list[ModuleItem]] = relationship(
        back_populates="module",
        cascade="all, delete-orphan",
        order_by="ModuleItem.position",
    )
    lessons: Mapped[list[Lesson]] = relationship(
        back_populates="module",
        cascade="all, delete-orphan",
    )
    quizzes: Mapped[list[Quiz]] = relationship(
        back_populates="module",
        cascade="all, delete-orphan",
    )
    depends_on: Mapped[list[ModuleDep]] = relationship(
        back_populates="module",
        cascade="all, delete-orphan",
        foreign_keys="ModuleDep.module_id",
    )


class ModuleItem(UUIDPrimaryKey):
    """
    Единственное место, где хранится порядок материалов модуля. Урок и тест
    идут одной лентой, поэтому и нумерация у них общая: раньше она была
    раздельной, а порядок собирался на клиенте и сервер его не знал.
    """

    __tablename__ = "module_items"
    __table_args__ = (
        CheckConstraint(
            "num_nonnulls(lesson_id, quiz_id, practice_set_id) = 1",
            name="module_items_one_target",
        ),
        position_unique("module_items", "module_id"),
        UniqueConstraint("lesson_id", name="uq_module_items_lesson_id"),
        UniqueConstraint("quiz_id", name="uq_module_items_quiz_id"),
        UniqueConstraint("practice_set_id", name="uq_module_items_practice_set_id"),
        ForeignKeyConstraint(
            ["lesson_id", "module_id"],
            ["lessons.id", "lessons.module_id"],
            name="fk_module_items_lesson_id_module_id_lessons",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["quiz_id", "module_id"],
            ["quizzes.id", "quizzes.module_id"],
            name="fk_module_items_quiz_id_module_id_quizzes",
            ondelete="CASCADE",
        ),
    )

    module_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("modules.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer(), default=0)
    lesson_id: Mapped[uuid.UUID | None]
    quiz_id: Mapped[uuid.UUID | None]
    practice_set_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("practice_sets.id", ondelete="CASCADE")
    )

    module: Mapped[Module] = relationship(back_populates="items")
    lesson: Mapped[Lesson | None] = relationship(viewonly=True)
    quiz: Mapped[Quiz | None] = relationship(viewonly=True)
    practice_set: Mapped[PracticeSet | None] = relationship(viewonly=True)


class ModuleDep(Base):
    """Ребро DAG прохождения: носит рекомендательный характер и не блокирует доступ."""

    __tablename__ = "module_deps"
    __table_args__ = (CheckConstraint("module_id <> depends_on_id", name="no_self_dep"),)

    module_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("modules.id", ondelete="CASCADE"),
        primary_key=True,
    )
    depends_on_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("modules.id", ondelete="CASCADE"),
        primary_key=True,
    )

    module: Mapped[Module] = relationship(back_populates="depends_on", foreign_keys=[module_id])
    depends_on: Mapped[Module] = relationship(foreign_keys=[depends_on_id])


class Lesson(UUIDPrimaryKey, SoftDeleteMixin):
    __tablename__ = "lessons"
    __table_args__ = (
        Index(
            "uq_lessons_module_id_slug",
            "module_id",
            "slug",
            unique=True,
            postgresql_where=text("NOT is_deleted"),
        ),
        UniqueConstraint("id", "module_id", name="uq_lessons_id_module_id"),
    )

    module_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("modules.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(120))
    est_minutes: Mapped[int | None] = mapped_column(SmallInteger())
    body_md: Mapped[str] = mapped_column(Text(), default="")
    body_html: Mapped[str] = mapped_column(Text(), default="")
    status: Mapped[ContentStatus] = status_column()

    module: Mapped[Module] = relationship(back_populates="lessons")
    interview_cards: Mapped[list[InterviewCard]] = relationship(
        back_populates="lesson",
        cascade="all, delete-orphan",
        order_by="InterviewCard.position",
    )


class InterviewCard(UUIDPrimaryKey):
    """Производная от блоков :::interview в body_md, напрямую не редактируется."""

    __tablename__ = "interview_cards"
    __table_args__ = (position_unique("interview_cards", "lesson_id"),)

    lesson_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lessons.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer(), default=0)
    question_md: Mapped[str] = mapped_column(Text())
    answer_md: Mapped[str] = mapped_column(Text())

    lesson: Mapped[Lesson] = relationship(back_populates="interview_cards")


Index("ix_modules_course_id", Module.course_id)
Index("ix_module_items_module_id", ModuleItem.module_id)
Index("ix_lessons_module_id", Lesson.module_id)
Index("ix_interview_cards_lesson_id", InterviewCard.lesson_id)
