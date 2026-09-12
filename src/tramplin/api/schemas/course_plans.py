import uuid_utils.compat as uuid

from tramplin.api.schemas.base import ApiModel
from tramplin.services.course_plan_schemas import (
    CoursePlanApply,
    CoursePlanLesson,
    CoursePlanModule,
    CoursePlanPracticeSet,
    CoursePlanQuestion,
    CoursePlanQuiz,
)

__all__ = [
    "CoursePlanApply",
    "CoursePlanApplyOut",
    "CoursePlanLesson",
    "CoursePlanModule",
    "CoursePlanPracticeSet",
    "CoursePlanQuestion",
    "CoursePlanQuiz",
]


class CoursePlanApplyOut(ApiModel):
    course_id: uuid.UUID
    course_slug: str
    created: int
    updated: int
    unchanged: int
