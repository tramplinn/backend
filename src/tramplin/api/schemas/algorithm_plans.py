from tramplin.api.schemas.base import ApiModel
from tramplin.services.algorithm_plan_schemas import (
    AlgorithmPlanApply,
    ProblemPlan,
    TemplatePlan,
    TestCasePlan,
)

__all__ = [
    "AlgorithmPlanApply",
    "AlgorithmPlanApplyOut",
    "ProblemPlan",
    "TemplatePlan",
    "TestCasePlan",
]


class AlgorithmPlanApplyOut(ApiModel):
    created: int
    updated: int
    unchanged: int
