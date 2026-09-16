import json

import httpx
import pytest

from tramplin.core.config import Settings
from tramplin.core.errors import RunnerUnavailableError
from tramplin.infrastructure.piston import PistonCodeRunner
from tramplin.services.contracts import RunRequest

RUNTIMES = [
    {"language": "python", "version": "3.12.0", "aliases": ["py"]},
    {"language": "javascript", "version": "20.11.1", "aliases": ["js"]},
    {"language": "typescript", "version": "5.0.3", "aliases": ["ts"]},
    {"language": "c++", "version": "10.2.0", "aliases": ["cpp"]},
    {"language": "java", "version": "15.0.2", "aliases": []},
    {"language": "csharp", "version": "6.12.0", "aliases": ["cs"]},
    {"language": "go", "version": "1.16.2", "aliases": []},
    {"language": "kotlin", "version": "1.8.20", "aliases": []},
    {"language": "ruby", "version": "3.0.1", "aliases": []},
]


async def test_piston_language_submission_and_result_contract(settings: Settings) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path == "/api/v2/runtimes":
            return httpx.Response(200, json=RUNTIMES)
        body = json.loads(request.content)
        assert body["language"] == "python"
        assert body["version"] == "*"
        assert body["run_memory_limit"] == 262144 * 1024
        return httpx.Response(
            200,
            json={
                "language": "python",
                "version": "3.12.0",
                "run": {
                    "stdout": "2\n",
                    "stderr": "",
                    "output": "2\n",
                    "code": 0,
                    "signal": None,
                    "memory": 1234 * 1024,
                    "message": None,
                    "status": None,
                    "cpu_time": 10,
                    "wall_time": 12,
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        runner = PistonCodeRunner(client, settings)
        languages = await runner.languages()
        assert {item.key for item in languages} == {
            "python",
            "javascript",
            "typescript",
            "cpp",
            "java",
            "csharp",
            "go",
            "kotlin",
        }
        assert await runner.languages() == languages  # cached

        job = await runner.submit(
            RunRequest("python", "print(2)", "1\n", "2\n", 1000, 262144, 65536)
        )
        result = await runner.result(job.id)
        assert result is not None
        assert result.verdict == "accepted"
        assert result.runtime_ms == 12 and result.memory_kb == 1234
        assert await runner.result(job.id) is None  # consumed
        assert sum(request.url.path == "/api/v2/runtimes" for request in calls) == 1


@pytest.mark.parametrize(
    ("run_step", "expected_output", "memory_limit_kb", "verdict"),
    [
        ({"code": 0, "signal": None, "status": None, "stdout": "2\n"}, "2\n", 1000, "accepted"),
        ({"code": 0, "signal": None, "status": None, "stdout": "3\n"}, "2\n", 1000, "wrong_answer"),
        ({"code": 0, "signal": None, "status": None, "stdout": "x"}, None, 1000, "accepted"),
        (
            {"code": None, "signal": "SIGKILL", "status": "TO", "stdout": ""},
            None,
            1000,
            "time_limit",
        ),
        (
            {"code": None, "signal": "SIGKILL", "status": "OL", "stdout": ""},
            None,
            1000,
            "output_limit",
        ),
        ({"code": 1, "signal": None, "status": None, "stdout": ""}, None, 1000, "runtime_error"),
        (
            {"code": None, "signal": "SIGKILL", "status": None, "stdout": "", "memory": 2_000_000},
            None,
            1000,
            "memory_limit",
        ),
    ],
)
async def test_piston_verdict_mapping(
    settings: Settings,
    run_step: dict[str, object],
    expected_output: str | None,
    memory_limit_kb: int,
    verdict: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v2/runtimes":
            return httpx.Response(200, json=RUNTIMES)
        return httpx.Response(
            200, json={"language": "python", "version": "3.12.0", "run": run_step}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        runner = PistonCodeRunner(client, settings)
        job = await runner.submit(
            RunRequest("python", "x", "", expected_output, 1000, memory_limit_kb, 65536)
        )
        result = await runner.result(job.id)
        assert result is not None
        assert result.verdict == verdict


async def test_piston_reports_compile_error_despite_mirrored_run(settings: Settings) -> None:
    """A failed compile still gets a `run` object (Piston mirrors compile's exit
    info into it instead of omitting it) — the verdict must come from `compile`."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v2/runtimes":
            return httpx.Response(200, json=RUNTIMES)
        failed_step = {
            "stdout": "",
            "stderr": "error: expected ';'",
            "code": 1,
            "signal": None,
            "output": "error: expected ';'",
            "status": "RE",
        }
        return httpx.Response(
            200,
            json={
                "language": "cpp",
                "version": "10.2.0",
                "compile": failed_step,
                "run": failed_step,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        runner = PistonCodeRunner(client, settings)
        job = await runner.submit(RunRequest("cpp", "bad", "", None, 1000, 1000, 65536))
        result = await runner.result(job.id)
        assert result is not None
        assert result.verdict == "compile_error"
        assert result.compile_output == "error: expected ';'"


async def test_piston_rejects_language_not_installed(settings: Settings) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=RUNTIMES))
    ) as client:
        runner = PistonCodeRunner(client, settings)
        with pytest.raises(RunnerUnavailableError, match="недоступен"):
            await runner.submit(RunRequest("ruby", "x", "", None, 100, 100, 100))


async def test_piston_maps_unavailable_responses(settings: Settings) -> None:
    responses = iter(
        [
            httpx.Response(200, json={}),
            httpx.Response(500, text="secret failure"),
            httpx.Response(200, text="not-json"),
        ]
    )

    def handler(_: httpx.Request) -> httpx.Response:
        return next(responses)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        runner = PistonCodeRunner(client, settings)
        with pytest.raises(RunnerUnavailableError, match="языки"):
            await runner.languages()
        runner._languages = {"python": "python"}
        runner._languages_expire_at = float("inf")
        request = RunRequest("python", "x", "", None, 1000, 1000, 1000)
        with pytest.raises(RunnerUnavailableError, match="недоступна"):
            await runner.submit(request)
        with pytest.raises(RunnerUnavailableError, match="недоступна"):
            await runner.submit(request)
