import uuid_utils.compat as uuid

from tramplin.api.schemas.plans import PlanReportOut
from tramplin.services.course_plan_schemas import (
    CoursePlanApply,
    CoursePlanLesson,
    CoursePlanModule,
    CoursePlanPracticeSet,
    CoursePlanQuestion,
    CoursePlanQuiz,
    PracticeSetPlanApply,
)

__all__ = [
    "CoursePlanApply",
    "CoursePlanApplyOut",
    "CoursePlanLesson",
    "CoursePlanModule",
    "CoursePlanPracticeSet",
    "CoursePlanPreviewOut",
    "CoursePlanQuestion",
    "CoursePlanQuiz",
    "PracticeSetPlanApply",
    "PracticeSetPlanOut",
]


class CoursePlanPreviewOut(PlanReportOut):
    course_slug: str


class CoursePlanApplyOut(PlanReportOut):
    course_id: uuid.UUID
    course_slug: str


class PracticeSetPlanOut(PlanReportOut):
    course_slug: str
    module_slug: str
