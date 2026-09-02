import asyncio
import re
from datetime import timedelta
from time import monotonic
from typing import Any, Final

import httpx

from tramplin.core.config import Settings
from tramplin.core.errors import RunnerUnavailableError
from tramplin.services.contracts import (
    CodeRunner,
    RunnerJob,
    RunnerLanguage,
    RunRequest,
    RunResult,
)

LANGUAGE_PATTERNS: Final[dict[str, re.Pattern[str]]] = {
    "python": re.compile(r"^Python \(3", re.I),
    "javascript": re.compile(r"^JavaScript \(Node", re.I),
    "typescript": re.compile(r"^TypeScript", re.I),
    "cpp": re.compile(r"^C\+\+ \(GCC", re.I),
    "java": re.compile(r"^Java \((?:OpenJDK|JDK)", re.I),
    "csharp": re.compile(r"^C#", re.I),
    "go": re.compile(r"^Go ", re.I),
    "kotlin": re.compile(r"^Kotlin", re.I),
}


class Judge0CodeRunner(CodeRunner):
    """Judge0 adapter. Judge ids and tokens do not leave infrastructure."""

    def __init__(self, client: httpx.AsyncClient, settings: Settings) -> None:
        self._client = client
        self._base_url = settings.judge0_url.rstrip("/")
        token = settings.judge0_auth_token.get_secret_value()
        self._headers = {"X-Auth-Token": token} if token else {}
        self._language_ids: dict[str, int] = {}
        self._language_names: dict[str, str] = {}
        self._languages_expire_at = 0.0
        self._lock = asyncio.Lock()

    async def languages(self) -> list[RunnerLanguage]:
        await self._refresh_languages()
        return [
            RunnerLanguage(key=key, name=self._language_names[key])
            for key in LANGUAGE_PATTERNS
            if key in self._language_ids
        ]

    async def submit(self, request: RunRequest) -> RunnerJob:
        await self._refresh_languages()
        language_id = self._language_ids.get(request.language)
        if language_id is None:
            raise RunnerUnavailableError(
                "Выбранный язык сейчас недоступен", language=request.language
            )
        payload: dict[str, object] = {
            "language_id": language_id,
            "source_code": request.source_code,
            "stdin": request.stdin,
            "cpu_time_limit": request.time_limit_ms / 1000,
            "wall_time_limit": max(request.time_limit_ms / 500, 2.0),
            "memory_limit": request.memory_limit_kb,
            "max_file_size": max(1, request.output_limit_bytes // 1024),
            "enable_network": False,
        }
        if request.expected_output is not None:
            payload["expected_output"] = request.expected_output
        data = await self._request("POST", "/submissions", json=payload)
        token = data.get("token")
        if not isinstance(token, str) or not token:
            raise RunnerUnavailableError("Среда выполнения вернула некорректный ответ")
        return RunnerJob(token)

    async def result(self, job_id: str) -> RunResult | None:
        data = await self._request(
            "GET",
            f"/submissions/{job_id}?fields=status,stdout,stderr,compile_output,message,time,memory",
        )
        status = data.get("status")
        status_id = status.get("id") if isinstance(status, dict) else None
        if status_id in (1, 2):
            return None
        return RunResult(
            verdict=_normalize_status(status_id),
            stdout=_text(data.get("stdout")),
            stderr=_text(data.get("stderr")),
            compile_output=_text(data.get("compile_output")),
            message=_text(data.get("message")),
            runtime_ms=_milliseconds(data.get("time")),
            memory_kb=_integer(data.get("memory")),
        )

    async def _refresh_languages(self) -> None:
        if self._languages_expire_at > monotonic():
            return
        async with self._lock:
            if self._languages_expire_at > monotonic():
                return
            raw = await self._request("GET", "/languages/")
            if not isinstance(raw, list):
                raise RunnerUnavailableError("Не удалось получить языки среды выполнения")
            ids: dict[str, int] = {}
            names: dict[str, str] = {}
            for item in raw:
                if not isinstance(item, dict):
                    continue
                identifier, name = item.get("id"), item.get("name")
                if not isinstance(identifier, int) or not isinstance(name, str):
                    continue
                for key, pattern in LANGUAGE_PATTERNS.items():
                    if pattern.search(name):
                        ids[key], names[key] = identifier, name
                        break
            self._language_ids, self._language_names = ids, names
            self._languages_expire_at = monotonic() + timedelta(minutes=10).total_seconds()

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = await self._client.request(
                method, f"{self._base_url}{path}", headers=self._headers, **kwargs
            )
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise RunnerUnavailableError("Среда выполнения кода недоступна") from error


def _normalize_status(status_id: object) -> str:
    if status_id == 3:
        return "accepted"
    if status_id == 4:
        return "wrong_answer"
    if status_id == 5:
        return "time_limit"
    if status_id == 6:
        return "compile_error"
    if status_id == 8:
        return "output_limit"
    if status_id in (7, 9, 10, 11, 13, 14):
        return "runtime_error"
    if status_id == 12:
        return "internal_error"
    return "internal_error"


def _text(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _milliseconds(value: object) -> int | None:
    try:
        return round(float(str(value)) * 1000) if value is not None else None
    except ValueError:
        return None


def _integer(value: object) -> int | None:
    return value if isinstance(value, int) else None
