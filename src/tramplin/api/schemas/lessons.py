import uuid_utils.compat as uuid
from pydantic import Field

from tramplin.api.schemas.base import ApiModel
from tramplin.models.enums import ContentStatus


class LessonCreate(ApiModel):
    title: str = Field(min_length=1, max_length=200)
    slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=120)
    est_minutes: int | None = Field(default=None, ge=1, le=32767)
    body_md: str = ""
    status: ContentStatus = ContentStatus.DRAFT


class LessonUpdate(ApiModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    slug: str | None = Field(
        default=None,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
        max_length=120,
    )
    est_minutes: int | None = Field(default=None, ge=1, le=32767)
    body_md: str | None = None
    status: ContentStatus | None = None


class InterviewCardOut(ApiModel):
    id: uuid.UUID
    position: int
    question_md: str
    answer_md: str


class LessonOut(ApiModel):
    id: uuid.UUID
    module_id: uuid.UUID
    title: str
    slug: str
    est_minutes: int | None
    body_md: str
    body_html: str
    status: ContentStatus


class MarkdownPreviewIn(ApiModel):
    body_md: str


class InterviewCardPreviewOut(ApiModel):
    position: int
    question_md: str
    answer_md: str


class MarkdownPreviewOut(ApiModel):
    body_html: str
    interview_cards: list[InterviewCardPreviewOut]
