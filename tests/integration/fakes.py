"""Заглушки внешних систем для интеграционных тестов.

Настоящая здесь только Postgres: всё, что уходит в сеть за её пределы (S3, Piston,
LLM, OAuth-провайдеры), подменяется, иначе тесты зависели бы от чужих сервисов.
"""

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Any

import uuid_utils.compat as uuid
from pydantic import BaseModel

from tramplin.infrastructure.llm import ChatPrompt
from tramplin.models.enums import AssetMime
from tramplin.services.contracts import (
    OAuthProfile,
    RunnerJob,
    RunnerLanguage,
    RunRequest,
    RunResult,
)

PUBLIC_BASE_URL = "https://cdn.test/tramplin"

RUNNER_LANGUAGES = [
    RunnerLanguage(key, key.title())
    for key in ("python", "javascript", "typescript", "cpp", "java", "csharp", "go", "kotlin")
]


class FakeStorage:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, AssetMime]] = {}

    def public_url(self, key: str) -> str:
        return f"{PUBLIC_BASE_URL}/{key}"

    async def upload(self, key: str, body: bytes, mime: AssetMime) -> str:
        self.objects[key] = (body, mime)
        return self.public_url(key)

    async def delete(self, key: str) -> None:
        self.objects.pop(key, None)


class FakeCodeRunner:
    """Решение считается верным, если не содержит маркер ошибки."""

    FAILING_MARKER = "# wrong"

    def __init__(self) -> None:
        self.requests: list[RunRequest] = []
        self._results: dict[str, RunResult] = {}

    async def languages(self) -> list[RunnerLanguage]:
        return list(RUNNER_LANGUAGES)

    async def submit(self, request: RunRequest) -> RunnerJob:
        self.requests.append(request)
        job_id = str(uuid.uuid4())
        verdict = "wrong_answer" if self.FAILING_MARKER in request.source_code else "accepted"
        self._results[job_id] = RunResult(
            verdict=verdict,
            stdout=request.expected_output,
            runtime_ms=5,
            memory_kb=1024,
        )
        return RunnerJob(job_id)

    async def result(self, job_id: str) -> RunResult | None:
        return self._results.get(job_id)


@dataclass
class FakeLlmClient:
    deltas: list[str] = field(default_factory=lambda: ["Подсказка: ", "подумайте о хэше."])
    patch: dict[str, Any] = field(
        default_factory=lambda: {"explanation": "Сократил вступление.", "body_md": "# Кратко"}
    )
    prompts: list[ChatPrompt] = field(default_factory=list)

    async def stream(self, prompt: ChatPrompt) -> AsyncIterator[str]:
        self.prompts.append(prompt)
        for delta in self.deltas:
            yield delta

    async def structured[T: BaseModel](
        self, prompt: ChatPrompt, result_type: type[T], *, max_output_tokens: int
    ) -> T:
        self.prompts.append(prompt)
        return result_type.model_validate(self.patch)

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [[0.0] * 512 for _ in texts]

    async def aclose(self) -> None:
        return None


class FakeOAuthClient:
    """Код авторизации — это ключ в словаре профилей: тест сам решает, кто «вошёл»."""

    def __init__(self, name: str) -> None:
        self._name = name
        self.profiles: dict[str, OAuthProfile] = {}

    def authorize_url(self, state: str) -> str:
        return f"https://{self._name}.test/authorize?state={state}"

    async def exchange_code(self, code: str) -> str:
        return code

    async def fetch_profile(self, access_token: str) -> OAuthProfile:
        return self.profiles[access_token]


@dataclass
class Fakes:
    storage: FakeStorage = field(default_factory=FakeStorage)
    runner: FakeCodeRunner = field(default_factory=FakeCodeRunner)
    llm: FakeLlmClient = field(default_factory=FakeLlmClient)
    github: FakeOAuthClient = field(default_factory=lambda: FakeOAuthClient("github"))
    yandex: FakeOAuthClient = field(default_factory=lambda: FakeOAuthClient("yandex"))
    gitlab: FakeOAuthClient = field(default_factory=lambda: FakeOAuthClient("gitlab"))
