from typing import Literal

from pydantic import Field

from tramplin.api.schemas.algorithms import LANGUAGE_PATTERN
from tramplin.api.schemas.base import ApiModel
from tramplin.services.teacher_assistant import (
    AuthoringDocument,
    AuthoringPatch,
    TemplateItem,
    TestCaseItem,
)


class TestCaseIn(ApiModel):
    input: str = Field(max_length=20000)
    expected_output: str = Field(max_length=20000)
    is_sample: bool


class TemplateIn(ApiModel):
    language: str = Field(pattern=LANGUAGE_PATTERN)
    starter_code: str = Field(max_length=20000)
    solution_code: str = Field(max_length=20000)


class AuthoringDocumentIn(ApiModel):
    title: str = Field(max_length=200)
    body_md: str | None = Field(default=None, max_length=50000)
    statement_md: str | None = Field(default=None, max_length=50000)
    difficulty: Literal["easy", "medium", "hard"] | None = None
    tags: list[str] | None = Field(default=None, max_length=20)
    time_limit_ms: int | None = Field(default=None, ge=50, le=5000)
    memory_limit_kb: int | None = Field(default=None, ge=16384, le=524288)
    test_cases: list[TestCaseIn] | None = Field(default=None, max_length=50)
    templates: list[TemplateIn] | None = Field(default=None, max_length=8)

    def to_document(self) -> AuthoringDocument:
        data = self.model_dump()
        test_cases = data.pop("test_cases")
        templates = data.pop("templates")
        return AuthoringDocument(
            **data,
            test_cases=(
                [TestCaseItem(**item) for item in test_cases] if test_cases is not None else None
            ),
            templates=(
                [TemplateItem(**item) for item in templates] if templates is not None else None
            ),
        )


class TeacherAssistantIn(ApiModel):
    surface: Literal["lesson", "algorithm_problem"]
    instruction: str = Field(min_length=1, max_length=4000)
    document: AuthoringDocumentIn


class TeacherAssistantOut(AuthoringPatch):
    pass
