from typing import Any

from pydantic import Field

from tramplin.api.schemas.base import ApiModel


class ErrorOut(ApiModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
