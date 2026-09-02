import asyncio
from time import monotonic
from typing import TypedDict

from tramplin.core.errors import RunnerUnavailableError
from tramplin.services.contracts import CodeRunner, RunRequest, RunResult


class CaseResult(TypedDict):
    position: int | None
    verdict: str
    stdout: str | None
    stderr: str | None
    runtime_ms: int | None
    memory_kb: int | None


async def execute_and_wait(
    runner: CodeRunner,
    request: RunRequest,
    wait_seconds: float,
) -> RunResult:
    job = await runner.submit(request)
    return await wait_for_result(runner, job.id, wait_seconds)


async def wait_for_result(runner: CodeRunner, job_id: str, wait_seconds: float) -> RunResult:
    deadline = monotonic() + wait_seconds
    while monotonic() < deadline:
        result = await runner.result(job_id)
        if result is not None:
            return result
        await asyncio.sleep(0.2)
    raise RunnerUnavailableError("Среда выполнения не завершила работу вовремя")


def bounded_output(value: str | None, max_bytes: int) -> str | None:
    if value is None:
        return None
    raw = value.encode()
    if len(raw) <= max_bytes:
        return value
    return raw[:max_bytes].decode(errors="ignore") + "\n… output truncated"
