from datetime import datetime

import uuid_utils.compat as uuid
from pydantic import Field, field_validator

from tramplin.api.schemas.assets import AssetOut
from tramplin.api.schemas.base import ApiModel
from tramplin.models.enums import ContentStatus

SLUG_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"


def _photos_are_unique(value: list[uuid.UUID]) -> list[uuid.UUID]:
    if len(value) != len(set(value)):
        raise ValueError("photo_ids не должны повторяться")
    return value


class NewsCreate(ApiModel):
    title: str = Field(min_length=1, max_length=200)
    slug: str = Field(pattern=SLUG_PATTERN, max_length=120)
    summary: str | None = None
    body_md: str = ""
    status: ContentStatus = ContentStatus.DRAFT
    photo_ids: list[uuid.UUID] = Field(default_factory=list)

    _unique_photos = field_validator("photo_ids")(_photos_are_unique)


class NewsUpdate(ApiModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    slug: str | None = Field(default=None, pattern=SLUG_PATTERN, max_length=120)
    summary: str | None = None
    body_md: str | None = None
    status: ContentStatus | None = None
    photo_ids: list[uuid.UUID] | None = None

    @field_validator("photo_ids")
    @classmethod
    def photos_are_unique(cls, value: list[uuid.UUID] | None) -> list[uuid.UUID] | None:
        return None if value is None else _photos_are_unique(value)


class NewsOut(ApiModel):
    id: uuid.UUID
    title: str
    slug: str
    summary: str | None
    body_md: str
    status: ContentStatus
    published_at: datetime | None
    photos: list[AssetOut] = Field(default_factory=list)
