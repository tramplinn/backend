import asyncio
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import pytest

import tramplin.worker as worker
from tramplin.models.base import new_id


class SessionContext:
    def __init__(self, session: object) -> None:
        self.session = session

    async def __aenter__(self) -> object:
        return self.session

    async def __aexit__(self, *_: object) -> None:
        return None


async def test_execute_submission_passes_redelivery_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    session = object()
    repository = object()
    service = SimpleNamespace(process=AsyncMock())
    service_factory = Mock(return_value=service)
    monkeypatch.setattr(worker, "session_factory", lambda: SessionContext(session))
    monkeypatch.setattr(worker, "AlgorithmRepository", Mock(return_value=repository))
    monkeypatch.setattr(worker, "AlgorithmWorkerService", service_factory)
    submission_id = new_id()
    raw = SimpleNamespace(raw_message=SimpleNamespace(redelivered=True))

    await worker.execute_submission(
        worker.AlgorithmJobMessage(submission_id=submission_id),
        cast(Any, raw),
    )

    service_factory.assert_called_once_with(session, repository, worker.runner, worker.settings)
    service.process.assert_awaited_once_with(submission_id, redelivered=True)


async def test_relay_outbox_waits_when_nothing_was_dispatched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = object()
    dispatch = SimpleNamespace(dispatch_next=AsyncMock(return_value=False))
    monkeypatch.setattr(worker, "session_factory", lambda: SessionContext(session))
    monkeypatch.setattr(worker, "AlgorithmRepository", Mock(return_value=object()))
    monkeypatch.setattr(worker, "AlgorithmDispatchService", Mock(return_value=dispatch))
    sleep = AsyncMock(side_effect=asyncio.CancelledError)
    monkeypatch.setattr(worker.asyncio, "sleep", sleep)

    with pytest.raises(asyncio.CancelledError):
        await worker.relay_outbox()

    dispatch.dispatch_next.assert_awaited_once()
    sleep.assert_awaited_once_with(0.5)


async def test_relay_outbox_logs_and_retries_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BrokenContext(SessionContext):
        async def __aenter__(self) -> object:
            raise RuntimeError("database unavailable")

    monkeypatch.setattr(worker, "session_factory", lambda: BrokenContext(object()))
    log = Mock()
    monkeypatch.setattr(worker.logger, "exception", log)
    sleep = AsyncMock(side_effect=asyncio.CancelledError)
    monkeypatch.setattr(worker.asyncio, "sleep", sleep)

    with pytest.raises(asyncio.CancelledError):
        await worker.relay_outbox()

    log.assert_called_once_with("algorithm outbox relay failed")
    sleep.assert_awaited_once_with(2)


async def test_worker_lifecycle_starts_and_stops_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = Mock()
    task.cancel = Mock()
    created: list[Any] = []

    def create_task(coroutine: Any, *, name: str) -> Mock:
        created.append(coroutine)
        assert name == "algorithm-outbox-relay"
        coroutine.close()
        return task

    gather = AsyncMock()
    client = SimpleNamespace(aclose=AsyncMock())
    engine = SimpleNamespace(dispose=AsyncMock())
    monkeypatch.setattr(worker.asyncio, "create_task", create_task)
    monkeypatch.setattr(worker.asyncio, "gather", gather)
    monkeypatch.setattr(worker, "runner_client", client)
    monkeypatch.setattr(worker, "engine", engine)
    monkeypatch.setattr(worker, "relay_task", None)

    await worker.start_relay()
    await worker.stop_relay()

    assert len(created) == 1
    task.cancel.assert_called_once_with()
    gather.assert_awaited_once_with(task, return_exceptions=True)
    client.aclose.assert_awaited_once_with()
    engine.dispose.assert_awaited_once_with()
