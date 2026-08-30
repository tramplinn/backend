from datetime import datetime
from typing import Any

import uuid_utils.compat as uuid
from pydantic import Field

from tramplin.api.schemas.base import ApiModel


class LessonProgressOut(ApiModel):
    lesson_id: uuid.UUID
    completed_at: datetime


class QuizProgressOut(ApiModel):
    quiz_id: uuid.UUID
    score: int
    max_score: int
    passed: bool


class ModuleProgressOut(ApiModel):
    module_id: uuid.UUID
    completed_lessons: int
    total_lessons: int


class CourseProgressOut(ApiModel):
    course_id: uuid.UUID
    completed_lessons: int
    total_lessons: int
    modules: list[ModuleProgressOut]


class QuizAttemptCreate(ApiModel):
    answers: dict[str, Any] = Field(default_factory=dict)


class QuestionResultOut(ApiModel):
    question_id: uuid.UUID
    correct: bool
    explanation: str | None = None


class QuizAttemptOut(ApiModel):
    id: uuid.UUID
    quiz_id: uuid.UUID
    score: int
    max_score: int
    results: list[QuestionResultOut] = Field(default_factory=list)
