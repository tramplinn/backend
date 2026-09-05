import uuid_utils.compat as uuid
from pydantic import Field

from tramplin.api.schemas.base import ApiModel
from tramplin.api.schemas.modules import ModuleTreeOut
from tramplin.api.schemas.tags import TagOut
from tramplin.models.enums import ContentStatus


class CourseCreate(ApiModel):
    title: str = Field(min_length=1, max_length=200)
    slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=120)
    summary: str | None = None
    color: str | None = Field(default=None, max_length=16)
    est_hours: int | None = Field(default=None, ge=1, le=32767)
    cover_asset_id: uuid.UUID | None = None
    status: ContentStatus = ContentStatus.DRAFT
    tags: list[str] = Field(default_factory=list, max_length=30)


class CourseUpdate(ApiModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    slug: str | None = Field(
        default=None,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
        max_length=120,
    )
    summary: str | None = None
    color: str | None = Field(default=None, max_length=16)
    est_hours: int | None = Field(default=None, ge=1, le=32767)
    cover_asset_id: uuid.UUID | None = None
    status: ContentStatus | None = None
    tags: list[str] | None = Field(default=None, max_length=30)


class CourseOut(ApiModel):
    id: uuid.UUID
    title: str
    slug: str
    summary: str | None
    color: str | None
    est_hours: int | None
    cover_asset_id: uuid.UUID | None
    cover_url: str | None
    status: ContentStatus
    tags: list[TagOut]


class CourseTreeOut(CourseOut):
    modules: list[ModuleTreeOut] = Field(default_factory=list)
