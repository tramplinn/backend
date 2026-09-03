from datetime import datetime

import uuid_utils.compat as uuid
from pydantic import Field, field_validator

from tramplin.api.schemas.assets import AssetOut
from tramplin.api.schemas.base import ApiModel
from tramplin.models.enums import FeedbackStatus
from tramplin.services.feedback import MAX_ATTACHMENTS, MAX_MESSAGE


class FeedbackCreate(ApiModel):
    message: str = Field(min_length=1, max_length=MAX_MESSAGE)
    page_path: str | None = Field(default=None, max_length=512)
    attachment_ids: list[uuid.UUID] = Field(default_factory=list, max_length=MAX_ATTACHMENTS)

    @field_validator("message")
    @classmethod
    def message_is_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Сообщение не может быть пустым")
        return value

    @field_validator("attachment_ids")
    @classmethod
    def attachments_are_unique(cls, value: list[uuid.UUID]) -> list[uuid.UUID]:
        if len(value) != len(set(value)):
            raise ValueError("attachment_ids не должны повторяться")
        return value


class FeedbackStatusUpdate(ApiModel):
    status: FeedbackStatus


class FeedbackOut(ApiModel):
    id: uuid.UUID
    author_id: uuid.UUID | None
    message: str
    page_path: str | None
    status: FeedbackStatus
    attachments: list[AssetOut] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
