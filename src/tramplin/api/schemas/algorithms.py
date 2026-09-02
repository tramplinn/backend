from datetime import datetime

import uuid_utils.compat as uuid
from pydantic import Field, HttpUrl

from tramplin.api.schemas.base import ApiModel
from tramplin.models.enums import (
    AlgorithmDifficulty,
    AlgorithmProgressStatus,
    AlgorithmProvider,
    AlgorithmVerdict,
    ContentStatus,
    PracticeMode,
    PracticeSessionStatus,
    SubmissionKind,
    SubmissionStatus,
)

LANGUAGE_PATTERN = r"^(python|javascript|typescript|cpp|java|csharp|go|kotlin)$"


class ProblemCreate(ApiModel):
    provider: AlgorithmProvider = AlgorithmProvider.INTERNAL
    external_key: str | None = Field(default=None, max_length=200)
    external_url: HttpUrl | None = None
    title: str = Field(min_length=1, max_length=200)
    statement_md: str = ""
    difficulty: AlgorithmDifficulty
    topics: list[str] = Field(default_factory=list, max_length=30)
    time_limit_ms: int = Field(default=1000, ge=50, le=5000)
    memory_limit_kb: int = Field(default=262144, ge=16384, le=524288)
    status: ContentStatus = ContentStatus.DRAFT


class ProblemUpdate(ApiModel):
    provider: AlgorithmProvider | None = None
    external_key: str | None = Field(default=None, max_length=200)
    external_url: HttpUrl | None = None
    title: str | None = Field(default=None, min_length=1, max_length=200)
    statement_md: str | None = None
    difficulty: AlgorithmDifficulty | None = None
    topics: list[str] | None = Field(default=None, max_length=30)
    time_limit_ms: int | None = Field(default=None, ge=50, le=5000)
    memory_limit_kb: int | None = Field(default=None, ge=16384, le=524288)
    status: ContentStatus | None = None


class TestCaseCreate(ApiModel):
    position: int = Field(ge=0)
    input: str = ""
    expected_output: str
    is_sample: bool = False
    weight: int = Field(default=1, ge=1, le=100)


class TestCaseUpdate(ApiModel):
    position: int | None = Field(default=None, ge=0)
    input: str | None = None
    expected_output: str | None = None
    is_sample: bool | None = None
    weight: int | None = Field(default=None, ge=1, le=100)


class TestCaseOut(TestCaseCreate):
    id: uuid.UUID


class SampleCaseOut(ApiModel):
    position: int
    input: str
    expected_output: str


class TemplatePut(ApiModel):
    language: str = Field(pattern=LANGUAGE_PATTERN)
    starter_code: str = ""
    solution_code: str = ""


class TemplateAuthorOut(TemplatePut):
    validated_at: datetime | None


class TemplateStudentOut(ApiModel):
    language: str
    starter_code: str


class ProblemAuthorOut(ApiModel):
    id: uuid.UUID
    provider: AlgorithmProvider
    external_key: str | None
    external_url: str | None
    title: str
    statement_md: str
    statement_html: str
    difficulty: AlgorithmDifficulty
    topics: list[str]
    time_limit_ms: int
    memory_limit_kb: int
    status: ContentStatus
    test_cases: list[TestCaseOut]
    templates: list[TemplateAuthorOut]


class ProblemOut(ApiModel):
    id: uuid.UUID
    provider: AlgorithmProvider
    external_key: str | None
    external_url: str | None
    title: str
    statement_html: str
    difficulty: AlgorithmDifficulty
    topics: list[str]
    time_limit_ms: int
    memory_limit_kb: int
    samples: list[SampleCaseOut]
    templates: list[TemplateStudentOut]


class PracticeSetCreate(ApiModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = ""
    mode: PracticeMode = PracticeMode.PRACTICE
    duration_minutes: int | None = Field(default=None, ge=1, le=480)
    status: ContentStatus = ContentStatus.DRAFT


class PracticeSetUpdate(ApiModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    mode: PracticeMode | None = None
    duration_minutes: int | None = Field(default=None, ge=1, le=480)
    status: ContentStatus | None = None


class SetProblemAdd(ApiModel):
    problem_id: uuid.UUID
    recommended_minutes: int | None = Field(default=None, ge=1, le=480)


class SetProblemOut(ApiModel):
    problem_id: uuid.UUID
    position: int
    recommended_minutes: int | None
    title: str
    difficulty: AlgorithmDifficulty
    solved: bool = False


class PracticeSetOut(ApiModel):
    id: uuid.UUID
    title: str
    description: str
    mode: PracticeMode
    duration_minutes: int | None
    status: ContentStatus
    problems: list[SetProblemOut]


class ReorderProblems(ApiModel):
    problem_ids: list[uuid.UUID]


class PracticeSessionOut(ApiModel):
    id: uuid.UUID
    practice_set_id: uuid.UUID
    mode: PracticeMode
    status: PracticeSessionStatus
    started_at: datetime
    deadline_at: datetime | None
    completed_at: datetime | None
    reflection_md: str | None


class CompleteSession(ApiModel):
    reflection_md: str | None = Field(default=None, max_length=10000)


class SubmissionCreate(ApiModel):
    session_id: uuid.UUID
    language: str = Field(pattern=LANGUAGE_PATTERN)
    source_code: str = Field(min_length=1)


class RunCreate(SubmissionCreate):
    custom_input: str | None = Field(default=None, max_length=65536)


class RunCaseOut(ApiModel):
    position: int | None
    verdict: AlgorithmVerdict
    stdout: str | None
    stderr: str | None
    runtime_ms: int | None
    memory_kb: int | None


class SubmissionOut(ApiModel):
    id: uuid.UUID
    session_id: uuid.UUID
    problem_id: uuid.UUID
    kind: SubmissionKind
    language: str
    status: SubmissionStatus
    verdict: AlgorithmVerdict | None
    runtime_ms: int | None
    memory_kb: int | None
    failed_test: int | None
    stdout: str | None
    stderr: str | None
    safe_error: str | None
    cases: list[RunCaseOut] = Field(default_factory=list)
    created_at: datetime
    finished_at: datetime | None


class ReflectionUpdate(ApiModel):
    complexity_md: str | None = Field(default=None, max_length=5000)
    confidence: int | None = Field(default=None, ge=1, le=5)
    reflection_md: str | None = Field(default=None, max_length=10000)


class ProgressOut(ReflectionUpdate):
    problem_id: uuid.UUID
    status: AlgorithmProgressStatus
    attempts: int
    hints_used: int
    first_solved_at: datetime | None
    last_attempt_at: datetime | None


class RunnerLanguageOut(ApiModel):
    key: str
    name: str


class RunnerHealthOut(ApiModel):
    status: str
    languages: int


class RunnerQueueOut(ApiModel):
    queued: int
    running: int
    pending_outbox: int
