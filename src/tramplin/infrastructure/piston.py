from datetime import timedelta
from time import monotonic
from typing import Any, Final

import httpx
import uuid_utils.compat as uuid

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
        payload = {
            "language": LANGUAGE_IDS[request.language],
            "version": ANY_VERSION,
            "files": [{"content": request.source_code}],
            "stdin": request.stdin,
            "compile_timeout": 10_000,
            "run_timeout": max(request.time_limit_ms * 2, 2000),
            "compile_memory_limit": -1,
            "run_memory_limit": request.memory_limit_kb * 1024,
        }
        data = await self._request("POST", "/execute", json=payload)
        job_id = str(uuid.uuid4())
        self._results[job_id] = _to_result(data, request)
        return RunnerJob(job_id)

    async def result(self, job_id: str) -> RunResult | None:
        return self._results.pop(job_id, None)

    async def _refresh_languages(self) -> None:
        if self._languages_expire_at > monotonic():
            return
        raw = await self._request("GET", "/runtimes")
        if not isinstance(raw, list):
            raise RunnerUnavailableError("Не удалось получить языки среды выполнения")
        installed = {
            item.get("language") for item in raw if isinstance(item, dict) and item.get("language")
        }
        languages: dict[str, str] = {}
        for key, piston_language in LANGUAGE_IDS.items():
            if piston_language in installed:
                languages[key] = piston_language
        self._languages = languages
        self._languages_expire_at = monotonic() + timedelta(minutes=10).total_seconds()

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = await self._client.request(method, f"{self._base_url}{path}", **kwargs)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise RunnerUnavailableError("Среда выполнения кода недоступна") from error


def _to_result(data: dict[str, Any], request: RunRequest) -> RunResult:
    compile_step = data.get("compile") if isinstance(data.get("compile"), dict) else None
    run_step = data.get("run") if isinstance(data.get("run"), dict) else None
    if compile_step is not None and (
        compile_step.get("code") != 0 or compile_step.get("signal") is not None
    ):
        # A failed compile still gets a mirrored `run` object (same exit info as
        # `compile`) rather than an absent one, so this must be checked directly
        # instead of treating a missing `run` as the compile-failure signal.
        return RunResult(verdict="compile_error", compile_output=_text(compile_step.get("stderr")))
    if run_step is None:
        raise RunnerUnavailableError("Среда выполнения вернула некорректный ответ")
    memory_kb = _memory_kb(run_step.get("memory"))
    return RunResult(
        verdict=_verdict(run_step, request, memory_kb),
        stdout=_text(run_step.get("stdout")),
        stderr=_text(run_step.get("stderr")),
        compile_output=_text(compile_step.get("stderr")) if compile_step else None,
        message=_text(run_step.get("message")),
        runtime_ms=_integer(run_step.get("wall_time")),
        memory_kb=memory_kb,
    )


def _verdict(run_step: dict[str, Any], request: RunRequest, memory_kb: int | None) -> str:
    status = run_step.get("status")
    if status == "TO":
        return "time_limit"
    if status in _OUTPUT_LIMIT_STATUSES:
        return "output_limit"
    signal = run_step.get("signal")
    code = run_step.get("code")
    if signal is not None or code != 0:
        if memory_kb is not None and memory_kb >= request.memory_limit_kb:
            return "memory_limit"
        return "runtime_error"
    if request.expected_output is not None and not _output_matches(
        run_step.get("stdout"), request.expected_output
    ):
        return "wrong_answer"
    return "accepted"


def _output_matches(actual: object, expected: str) -> bool:
    return _normalize_output(actual if isinstance(actual, str) else "") == _normalize_output(
        expected
    )


def _normalize_output(text: str) -> list[str]:
    lines = text.rstrip("\n").split("\n")
    return [line.rstrip() for line in lines]


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _integer(value: object) -> int | None:
    return round(value) if isinstance(value, int | float) else None


def _memory_kb(value: object) -> int | None:
    return round(value / 1024) if isinstance(value, int | float) else None
