from pydantic import Field, HttpUrl

from tramplin.core.schema import ApiModel
from tramplin.models.enums import AlgorithmDifficulty, AlgorithmProvider

LANGUAGE_PATTERN = r"^(python|javascript|typescript|cpp|java|csharp|go|kotlin)$"
SLUG_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"


class TestCasePlan(ApiModel):
    position: int = Field(ge=0)
    input: str = ""
    expected_output: str
    is_sample: bool = False
    weight: int = Field(default=1, ge=1, le=100)


class TemplatePlan(ApiModel):
    language: str = Field(pattern=LANGUAGE_PATTERN)
    starter_code: str = ""
    solution_code: str = ""


class ProblemPlan(ApiModel):
    slug: str = Field(pattern=SLUG_PATTERN, max_length=120)
    provider: AlgorithmProvider = AlgorithmProvider.INTERNAL
    external_key: str | None = Field(default=None, max_length=200)
    external_url: HttpUrl | None = None
    title: str = Field(min_length=1, max_length=200)
    statement_md: str = ""
    difficulty: AlgorithmDifficulty
    tags: list[str] = Field(default_factory=list, max_length=30)
    time_limit_ms: int = Field(default=1000, ge=50, le=5000)
    memory_limit_kb: int = Field(default=262144, ge=16384, le=524288)
    test_cases: list[TestCasePlan] = Field(default_factory=list)
    templates: list[TemplatePlan] = Field(default_factory=list)


class AlgorithmPlanApply(ApiModel):
    problems: list[ProblemPlan] = Field(default_factory=list)
