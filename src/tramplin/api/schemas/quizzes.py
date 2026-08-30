from typing import Any

import uuid_utils.compat as uuid
from pydantic import Field

from tramplin.api.schemas.assets import AssetOut
from tramplin.api.schemas.base import ApiModel
from tramplin.models.enums import ContentStatus, QuestionType


class QuizCreate(ApiModel):
    title: str = Field(min_length=1, max_length=200)
    slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=120)
    lesson_id: uuid.UUID | None = None
    status: ContentStatus = ContentStatus.DRAFT


class QuizUpdate(ApiModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    slug: str | None = Field(
        default=None,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
        max_length=120,
    )
    lesson_id: uuid.UUID | None = None
    status: ContentStatus | None = None


class QuizQuestionCreate(ApiModel):
    position: int = Field(ge=0)
    prompt_md: str = Field(min_length=1)
    type: QuestionType
    options: list[Any] = Field(default_factory=list)
    answer: dict[str, Any]
    explain_md: str | None = None
    attachment_ids: list[uuid.UUID] = Field(default_factory=list)


class QuizQuestionUpdate(ApiModel):
    position: int | None = Field(default=None, ge=0)
    prompt_md: str | None = Field(default=None, min_length=1)
    type: QuestionType | None = None
    options: list[Any] | None = None
    answer: dict[str, Any] | None = None
    explain_md: str | None = None
    attachment_ids: list[uuid.UUID] | None = None


class QuizQuestionOut(ApiModel):
    id: uuid.UUID
    position: int
    prompt_md: str
    type: QuestionType
    options: list[Any]
    attachments: list[AssetOut] = Field(default_factory=list)


class QuizQuestionAuthorOut(QuizQuestionOut):
    answer: dict[str, Any]
    explain_md: str | None


class QuizOut(ApiModel):
    id: uuid.UUID
    module_id: uuid.UUID
    lesson_id: uuid.UUID | None
    title: str
    slug: str
    status: ContentStatus
    questions: list[QuizQuestionOut] = Field(default_factory=list)


class QuizAuthorOut(ApiModel):
    id: uuid.UUID
    module_id: uuid.UUID
    lesson_id: uuid.UUID | None
    title: str
    slug: str
    status: ContentStatus
    questions: list[QuizQuestionAuthorOut] = Field(default_factory=list)
