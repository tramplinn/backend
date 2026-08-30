from typing import Literal

from pydantic import Field

from tramplin.api.schemas.base import ApiModel


class TutorTurnIn(ApiModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=8000)


class TutorAskIn(ApiModel):
    """Диалог приходит целиком: на сервере история не хранится."""

    messages: list[TutorTurnIn] = Field(min_length=1, max_length=50)
