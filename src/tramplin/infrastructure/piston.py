from datetime import timedelta
from time import monotonic
from typing import Any, Final

import httpx
import uuid_utils.compat as uuid
from pydantic import BaseModel, TypeAdapter, ValidationError

from tramplin.core.config import Settings
from tramplin.core.errors import RunnerUnavailableError
from tramplin.services.contracts import (
    CodeRunner,
    RunnerJob,
    RunnerLanguage,
    RunRequest,
    RunResult,
)

# Piston resolves "*" to the highest installed version for the language, so we
# never need to track exact package versions ourselves (see /api/v2/packages).
ANY_VERSION: Final = "*"

# Our language keys -> Piston's runtime "language" identifiers (from packages/*/metadata.json).
LANGUAGE_IDS: Final[dict[str, str]] = {
    "python": "python",
    "javascript": "javascript",
    "typescript": "typescript",
    "cpp": "c++",
    "java": "java",
    "csharp": "csharp",
    "go": "go",
    "kotlin": "kotlin",
}

# Piston kills the process and reports these when the *server-wide*
# PISTON_OUTPUT_MAX_SIZE is hit, independent of our per-problem output limit.
_OUTPUT_LIMIT_STATUSES: Final = {"OL", "EL"}


class _PistonRuntime(BaseModel):
    language: str


class _PistonFile(BaseModel):
    content: str


class _PistonExecuteRequest(BaseModel):
    language: str
    version: str = ANY_VERSION
    files: list[_PistonFile]
    stdin: str
    compile_timeout: int = 10_000
    run_timeout: int
    compile_memory_limit: int = -1
    run_memory_limit: int

    @classmethod
    def from_run_request(cls, request: RunRequest) -> _PistonExecuteRequest:
        return cls(
            language=LANGUAGE_IDS[request.language],
            files=[_PistonFile(content=request.source_code)],
            stdin=request.stdin,
            run_timeout=max(request.time_limit_ms * 2, 2000),
            run_memory_limit=request.memory_limit_kb * 1024,
        )


class _PistonStep(BaseModel):
    stdout: str = ""
    stderr: str = ""
    code: int | None = None
    signal: str | None = None
    status: str | None = None
    message: str | None = None
    wall_time: int | float | None = None
    memory: int | float | None = None


class _PistonExecuteResponse(BaseModel):
    compile: _PistonStep | None = None
    run: _PistonStep


_RUNTIMES_ADAPTER: Final = TypeAdapter(list[_PistonRuntime])


class PistonCodeRunner(CodeRunner):
    """Piston adapter. Piston executes synchronously, so submit() runs the job
    immediately and result() just hands back the cached RunResult."""

    def __init__(self, client: httpx.AsyncClient, settings: Settings) -> None:
        self._client = client
        self._base_url = settings.piston_url.rstrip("/") + "/api/v2"
        self._languages: dict[str, str] = {}
        self._languages_expire_at = 0.0
        self._results: dict[str, RunResult] = {}

    async def languages(self) -> list[RunnerLanguage]:
        await self._refresh_languages()
        return [RunnerLanguage(key=key, name=name) for key, name in self._languages.items()]

    async def submit(self, request: RunRequest) -> RunnerJob:
        await self._refresh_languages()
        if request.language not in self._languages:
            raise RunnerUnavailableError(
                "Выбранный язык сейчас недоступен", language=request.language
            )
        payload = _PistonExecuteRequest.from_run_request(request)
        raw = await self._request("POST", "/execute", json=payload.model_dump())
        try:
            response = _PistonExecuteResponse.model_validate(raw)
        except ValidationError as error:
            raise RunnerUnavailableError("Среда выполнения вернула некорректный ответ") from error
        job_id = str(uuid.uuid4())
        self._results[job_id] = _to_result(response, request)
        return RunnerJob(job_id)

    async def result(self, job_id: str) -> RunResult | None:
        return self._results.pop(job_id, None)

    async def _refresh_languages(self) -> None:
        if self._languages_expire_at > monotonic():
            return
        raw = await self._request("GET", "/runtimes")
        try:
            runtimes = _RUNTIMES_ADAPTER.validate_python(raw)
        except ValidationError as error:
            raise RunnerUnavailableError("Не удалось получить языки среды выполнения") from error
        installed = {item.language for item in runtimes}
        self._languages = {
            key: piston_language
            for key, piston_language in LANGUAGE_IDS.items()
            if piston_language in installed
        }
        self._languages_expire_at = monotonic() + timedelta(minutes=10).total_seconds()

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = await self._client.request(method, f"{self._base_url}{path}", **kwargs)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise RunnerUnavailableError("Среда выполнения кода недоступна") from error


def _to_result(response: _PistonExecuteResponse, request: RunRequest) -> RunResult:
    compile_step = response.compile
    run_step = response.run
    if compile_step is not None and (compile_step.code != 0 or compile_step.signal is not None):
        # A failed compile still gets a mirrored `run` object (same exit info as
        # `compile`) rather than an absent one, so this must be checked directly
        # instead of treating a missing `run` as the compile-failure signal.
        return RunResult(verdict="compile_error", compile_output=compile_step.stderr or None)
    memory_kb = round(run_step.memory / 1024) if run_step.memory is not None else None
    runtime_ms = round(run_step.wall_time) if run_step.wall_time is not None else None
    return RunResult(
        verdict=_verdict(run_step, request, memory_kb),
        stdout=run_step.stdout or None,
        stderr=run_step.stderr or None,
        compile_output=compile_step.stderr or None if compile_step else None,
        message=run_step.message or None,
        runtime_ms=runtime_ms,
        memory_kb=memory_kb,
    )


def _verdict(run_step: _PistonStep, request: RunRequest, memory_kb: int | None) -> str:
    if run_step.status == "TO":
        return "time_limit"
    if run_step.status in _OUTPUT_LIMIT_STATUSES:
        return "output_limit"
    if run_step.signal is not None or run_step.code != 0:
        if memory_kb is not None and memory_kb >= request.memory_limit_kb:
            return "memory_limit"
        return "runtime_error"
    if request.expected_output is not None and not _output_matches(
        run_step.stdout, request.expected_output
    ):
        return "wrong_answer"
    return "accepted"


def _output_matches(actual: str, expected: str) -> bool:
    return _normalize_output(actual) == _normalize_output(expected)


def _normalize_output(text: str) -> list[str]:
    return [line.rstrip() for line in text.rstrip("\n").split("\n")]
