from dataclasses import dataclass
from typing import Literal, Protocol

import uuid_utils.compat as uuid

from tramplin.models.enums import IdentityProvider, RecommendationEntityType

StatePurpose = Literal["login", "link"]


class Transaction(Protocol):
    async def commit(self) -> None: ...

    async def flush(self) -> None: ...


@dataclass(frozen=True, slots=True)
class PageResult[T]:
    items: list[T]
    total: int
    limit: int
    offset: int


@dataclass(frozen=True, slots=True)
class ProfileStats:
    completed_lessons: int
    passed_quizzes: int
    solved_algorithms: int


@dataclass(frozen=True, slots=True)
class CourseActivity:
    slug: str
    title: str
    color: str | None
    completed_lessons: int
    total_lessons: int


@dataclass(frozen=True, slots=True)
class OAuthProfile:
    """Общий знаменатель профилей провайдеров: больше нам от них ничего не нужно."""

    provider_id: str
    login: str
    name: str | None
    email: str | None
    avatar_url: str | None


@dataclass(frozen=True, slots=True)
class OAuthState:
    provider: IdentityProvider
    purpose: StatePurpose
    user_id: str | None = None
    next_path: str = "/"


@dataclass(frozen=True, slots=True)
class RunnerLanguage:
    key: str
    name: str


@dataclass(frozen=True, slots=True)
class RunRequest:
    language: str
    source_code: str
    stdin: str
    expected_output: str | None
    time_limit_ms: int
    memory_limit_kb: int
    output_limit_bytes: int


@dataclass(frozen=True, slots=True)
class RunnerJob:
    id: str


@dataclass(frozen=True, slots=True)
class RunResult:
    verdict: str
    stdout: str | None = None
    stderr: str | None = None
    compile_output: str | None = None
    message: str | None = None
    runtime_ms: int | None = None
    memory_kb: int | None = None


class CodeRunner(Protocol):
    async def languages(self) -> list[RunnerLanguage]: ...

    async def submit(self, request: RunRequest) -> RunnerJob: ...

    async def result(self, job_id: str) -> RunResult | None: ...


class SubmissionQueue(Protocol):
    async def publish(self, submission_id: uuid.UUID) -> None: ...


class EmbeddingQueue(Protocol):
    async def publish(
        self, entity_type: RecommendationEntityType, entity_id: uuid.UUID
    ) -> None: ...
