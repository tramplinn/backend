import json

import httpx
import pytest

from tramplin.core.config import Settings
from tramplin.core.errors import RunnerUnavailableError
from tramplin.infrastructure.judge0 import (
    Judge0CodeRunner,
    _integer,
    _milliseconds,
    _normalize_status,
    _text,
)
from tramplin.services.contracts import RunRequest

LANGUAGES = [
    {"id": 1, "name": "Python (3.13.0)"},
    {"id": 2, "name": "JavaScript (Node.js 22.0)"},
    {"id": 3, "name": "TypeScript (5.6)"},
    {"id": 4, "name": "C++ (GCC 14.1)"},
    {"id": 5, "name": "Java (OpenJDK 21)"},
    {"id": 6, "name": "C# (Mono 6.12)"},
    {"id": 7, "name": "Go (1.23)"},
    {"id": 8, "name": "Kotlin (2.0)"},
    {"id": "bad", "name": "ignored"},
    "ignored",
]


async def test_judge0_language_submission_and_result_contract(settings: Settings) -> None:
    calls: list[httpx.Request] = []
    result_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal result_calls
        calls.append(request)
        if request.url.path == "/languages/":
            return httpx.Response(200, json=LANGUAGES)
        if request.method == "POST":
            body = json.loads(request.content)
            assert body["language_id"] == 1
            assert body["expected_output"] == "2\n"
            assert body["enable_network"] is False
            return httpx.Response(201, json={"token": "judge-secret"})
        result_calls += 1
        if result_calls == 1:
            return httpx.Response(200, json={"status": {"id": 2}})
        return httpx.Response(
            200,
            json={
                "status": {"id": 3},
                "stdout": "2\n",
                "stderr": None,
                "compile_output": None,
                "message": "ok",
                "time": "0.012",
                "memory": 1234,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        runner = Judge0CodeRunner(client, settings)
        languages = await runner.languages()
        assert [item.key for item in languages] == [
            "python",
            "javascript",
            "typescript",
            "cpp",
            "java",
            "csharp",
            "go",
            "kotlin",
        ]
        assert await runner.languages() == languages  # cached
        job = await runner.submit(
            RunRequest("python", "print(2)", "1\n", "2\n", 1000, 262144, 65536)
        )
        assert job.id == "judge-secret"
        assert await runner.result(job.id) is None
        result = await runner.result(job.id)
        assert result is not None
        assert result.verdict == "accepted"
        assert result.runtime_ms == 12 and result.memory_kb == 1234
        assert sum(request.url.path == "/languages/" for request in calls) == 1


@pytest.mark.parametrize(
    ("status_id", "verdict"),
    [
        (3, "accepted"),
        (4, "wrong_answer"),
        (5, "time_limit"),
        (6, "compile_error"),
        (7, "runtime_error"),
        (8, "output_limit"),
        (12, "internal_error"),
        (999, "internal_error"),
    ],
)
def test_judge0_status_normalization(status_id: int, verdict: str) -> None:
    assert _normalize_status(status_id) == verdict


async def test_judge0_maps_invalid_and_unavailable_responses(settings: Settings) -> None:
    responses = iter(
        [
            httpx.Response(200, json={}),
            httpx.Response(200, json=[]),
            httpx.Response(200, json={"token": None}),
            httpx.Response(500, text="secret failure"),
            httpx.Response(200, text="not-json"),
        ]
    )

    def handler(_: httpx.Request) -> httpx.Response:
        return next(responses)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        runner = Judge0CodeRunner(client, settings)
        with pytest.raises(RunnerUnavailableError, match="языки"):
            await runner.languages()
        assert await runner.languages() == []
        runner._language_ids["python"] = 1
        runner._languages_expire_at = float("inf")
        request = RunRequest("python", "x", "", None, 1000, 1000, 1000)
        with pytest.raises(RunnerUnavailableError, match="некорректный"):
            await runner.submit(request)
        with pytest.raises(RunnerUnavailableError, match="недоступна"):
            await runner.result("x")
        with pytest.raises(RunnerUnavailableError, match="недоступна"):
            await runner.result("x")

    assert _text("x") == "x" and _text(1) is None
    assert _milliseconds("0.5") == 500 and _milliseconds("bad") is None
    assert _milliseconds(None) is None
    assert _integer(4) == 4 and _integer("4") is None


async def test_judge0_rejects_language_not_in_allowlist(settings: Settings) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=LANGUAGES))
    ) as client:
        runner = Judge0CodeRunner(client, settings)
        with pytest.raises(RunnerUnavailableError, match="недоступен"):
            await runner.submit(RunRequest("ruby", "x", "", None, 100, 100, 100))
