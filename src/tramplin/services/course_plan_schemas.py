from typing import Any, Literal, Self

import uuid_utils.compat as uuid
from pydantic import Field, model_validator

from tramplin.core.schema import ApiModel

SLUG_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"


class CoursePlanLesson(ApiModel):
    title: str = Field(min_length=1, max_length=200)
    slug: str = Field(pattern=SLUG_PATTERN, max_length=120)
    body_md: str = ""
    est_minutes: int | None = Field(default=None, ge=1, le=32767)


class CoursePlanQuestion(ApiModel):
    position: int = Field(ge=0)
    prompt_md: str = Field(min_length=1)
    type: Literal["single", "multiple", "text", "matching", "grouping", "file"]
    options: list[Any] = Field(default_factory=list)
    answer: dict[str, Any]
    explain_md: str | None = None
    attachment_ids: list[uuid.UUID] = Field(default_factory=list)


class CoursePlanQuiz(ApiModel):
    title: str = Field(min_length=1, max_length=200)
    slug: str = Field(pattern=SLUG_PATTERN, max_length=120)
    lesson_slug: str | None = Field(default=None, pattern=SLUG_PATTERN, max_length=120)
    questions: list[CoursePlanQuestion] = Field(default_factory=list)


class CoursePlanPracticeSet(ApiModel):
    """Набор практики не имеет slug (его нет и в БД): в пределах модуля он matched по title."""

    title: str = Field(min_length=1, max_length=200)
    description: str = ""
    mode: Literal["practice", "mock_interview"] = "practice"
    duration_minutes: int | None = Field(default=None, ge=1, le=480)
    problem_slugs: list[str] = Field(default_factory=list)


class CoursePlanModule(ApiModel):
    title: str = Field(min_length=1, max_length=200)
    slug: str = Field(pattern=SLUG_PATTERN, max_length=120)
    summary: str | None = None
    lessons: list[CoursePlanLesson] = Field(default_factory=list)
    quizzes: list[CoursePlanQuiz] = Field(default_factory=list)
    practice_sets: list[CoursePlanPracticeSet] = Field(default_factory=list)
    content_order: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_slugs_and_order(self) -> Self:
        lesson_slugs = [item.slug for item in self.lessons]
        quiz_slugs = [item.slug for item in self.quizzes]
        practice_titles = [item.title for item in self.practice_sets]
        all_slugs = lesson_slugs + quiz_slugs + practice_titles
        if len(set(lesson_slugs)) != len(lesson_slugs):
            raise ValueError("lesson slug должен быть уникальным внутри модуля")
        if len(set(quiz_slugs)) != len(quiz_slugs):
            raise ValueError("quiz slug должен быть уникальным внутри модуля")
        if len(set(practice_titles)) != len(practice_titles):
            raise ValueError("practice set title должен быть уникальным внутри модуля")
        if self.content_order and (
            len(self.content_order) != len(all_slugs) or set(self.content_order) != set(all_slugs)
        ):
            raise ValueError(
                "content_order должен содержать каждый lesson/quiz slug и practice set title "
                "ровно один раз"
            )
        return self


class CoursePlanApply(ApiModel):
    title: str = Field(min_length=1, max_length=200)
    slug: str = Field(pattern=SLUG_PATTERN, max_length=120)
    summary: str | None = None
    color: str | None = Field(default=None, max_length=16)
    est_hours: int | None = Field(default=None, ge=1, le=32767)
    modules: list[CoursePlanModule] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_module_slugs(self) -> Self:
        slugs = [item.slug for item in self.modules]
        if len(set(slugs)) != len(slugs):
            raise ValueError("module slug должен быть уникальным внутри курса")
        return self
