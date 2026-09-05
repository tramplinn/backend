from typing import Literal

from pydantic import Field

from tramplin.api.schemas.base import ApiModel
from tramplin.services.teacher_assistant import AuthoringDocument, AuthoringPatch


class AuthoringDocumentIn(ApiModel):
    title: str = Field(max_length=200)
    body_md: str | None = Field(default=None, max_length=50000)
    statement_md: str | None = Field(default=None, max_length=50000)
    difficulty: Literal["easy", "medium", "hard"] | None = None
    topics: list[str] | None = Field(default=None, max_length=20)
    time_limit_ms: int | None = Field(default=None, ge=50, le=5000)
    memory_limit_kb: int | None = Field(default=None, ge=16384, le=524288)

    def to_document(self) -> AuthoringDocument:
        return AuthoringDocument(**self.model_dump())


class TeacherAssistantIn(ApiModel):
    surface: Literal["lesson", "algorithm_problem"]
    instruction: str = Field(min_length=1, max_length=4000)
    document: AuthoringDocumentIn


class TeacherAssistantOut(AuthoringPatch):
    pass
