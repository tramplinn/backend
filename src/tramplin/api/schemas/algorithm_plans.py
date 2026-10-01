from typing import Any

from pydantic import Field

from tramplin.api.schemas.base import ApiModel
from tramplin.api.schemas.plans import PlanReportOut
from tramplin.services.algorithm_plan_schemas import (
    AlgorithmPlanApply,
    ProblemPlan,
    TemplatePlan,
    TestCasePlan,
)

__all__ = [
    "AlgorithmPlanApply",
    "AlgorithmPlanApplyOut",
    "AlgorithmPlanPreviewOut",
    "ProblemPlan",
    "TemplatePlan",
    "TemplateValidationOut",
    "TestCasePlan",
]


class TemplateValidationOut(ApiModel):
    problem_slug: str
    language: str
    passed: bool
    message: str | None = Field(default=None, description="Причина отказа, если не прошло.")
    details: dict[str, Any] = Field(
        default_factory=dict, description="Например, test_position и verdict упавшего теста."
    )


class AlgorithmPlanPreviewOut(PlanReportOut):
    pass


class AlgorithmPlanApplyOut(PlanReportOut):
    template_validations: list[TemplateValidationOut] = Field(
        default_factory=list,
        description="Результаты прогона эталонных решений (только при validate_templates=true).",
    )
