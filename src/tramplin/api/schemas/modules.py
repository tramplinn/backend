from typing import Annotated, Literal

import uuid_utils.compat as uuid
from pydantic import Field, field_validator

from tramplin.api.schemas.base import ApiModel
from tramplin.api.schemas.lessons import LessonOut
from tramplin.api.schemas.quizzes import QuizOut
from tramplin.models.enums import ContentStatus, PracticeMode


class ModuleCreate(ApiModel):
    title: str = Field(min_length=1, max_length=200)
    slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=120)
    summary: str | None = None
    position: int = Field(ge=0)
    status: ContentStatus = ContentStatus.DRAFT


class ModuleUpdate(ApiModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    slug: str | None = Field(
        default=None,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
        max_length=120,
    )
    summary: str | None = None
    position: int | None = Field(default=None, ge=0)
    status: ContentStatus | None = None


class ModuleOut(ApiModel):
    id: uuid.UUID
    course_id: uuid.UUID
    title: str
    slug: str
    summary: str | None
    position: int
    status: ContentStatus


class ItemsOrder(ApiModel):
    """Порядок задаётся целиком: сервер расставит position по индексам списка."""

    ids: list[uuid.UUID]

    @field_validator("ids")
    @classmethod
    def ids_are_unique(cls, value: list[uuid.UUID]) -> list[uuid.UUID]:
        if len(value) != len(set(value)):
            raise ValueError("ids не должны повторяться")
        return value


class ModuleContentItem(ApiModel):
    id: uuid.UUID
    position: int


class LessonModuleItemOut(ModuleContentItem):
    kind: Literal["lesson"] = "lesson"
    lesson: LessonOut


class QuizModuleItemOut(ModuleContentItem):
    kind: Literal["quiz"] = "quiz"
    quiz: QuizOut


class PracticeSetModuleSummary(ApiModel):
    id: uuid.UUID
    title: str
    description: str
    mode: PracticeMode
    duration_minutes: int | None
    status: ContentStatus


class PracticeModuleItemOut(ModuleContentItem):
    kind: Literal["practice"] = "practice"
    practice_set: PracticeSetModuleSummary


ModuleContentItemOut = Annotated[
    LessonModuleItemOut | QuizModuleItemOut | PracticeModuleItemOut,
    Field(discriminator="kind"),
]


class ModuleContentOrder(ApiModel):
    """Лента модуля целиком: уроки и тесты вперемешку, как их видит студент."""

    ids: list[uuid.UUID]

    @field_validator("ids")
    @classmethod
    def items_are_unique(cls, value: list[uuid.UUID]) -> list[uuid.UUID]:
        if len(value) != len(set(value)):
            raise ValueError("ids не должны повторяться")
        return value


class ModuleDependencyCreate(ApiModel):
    depends_on_id: uuid.UUID


class ModuleDependencyOut(ApiModel):
    module_id: uuid.UUID
    depends_on_id: uuid.UUID


class ModuleTreeOut(ModuleOut):
    items: list[ModuleContentItemOut] = Field(default_factory=list)
