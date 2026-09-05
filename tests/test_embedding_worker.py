import asyncio
import sys
from collections.abc import AsyncIterator
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

import tramplin.embedding_worker as embedding_worker
from tramplin.core.config import Settings
from tramplin.models.base import new_id
from tramplin.models.enums import RecommendationEntityType


class SessionContext:
    def __init__(self, session: object) -> None:
        self.session = session

    async def __aenter__(self) -> object:
        return self.session

    async def __aexit__(self, *_: object) -> None:
        return None


@pytest.fixture
async def runtime(settings: Settings) -> AsyncIterator[embedding_worker.EmbeddingWorkerApplication]:
    application = embedding_worker.create_worker(settings)
    yield application
    await application.llm_client.aclose()
    await application.engine.dispose()


async def test_execute_embedding_job_calls_service(
    monkeypatch: pytest.MonkeyPatch,
    runtime: embedding_worker.EmbeddingWorkerApplication,
) -> None:
    session = object()
    repository = object()
    service = SimpleNamespace(process=AsyncMock())
    service_factory = Mock(return_value=service)
    monkeypatch.setattr(runtime, "session_factory", lambda: SessionContext(session))
    monkeypatch.setattr(embedding_worker, "RecommendationRepository", Mock(return_value=repository))
    monkeypatch.setattr(embedding_worker, "EmbeddingWorkerService", service_factory)
    entity_id = new_id()

    await runtime.execute_embedding_job(
        embedding_worker.EmbeddingJobMessage(
            entity_type=RecommendationEntityType.ALGORITHM_PROBLEM,
            entity_id=entity_id,
        )
    )

    service_factory.assert_called_once_with(session, repository, runtime.llm_client)
    service.process.assert_awaited_once_with(RecommendationEntityType.ALGORITHM_PROBLEM, entity_id)


async def test_relay_outbox_waits_when_nothing_was_dispatched(
    monkeypatch: pytest.MonkeyPatch,
    runtime: embedding_worker.EmbeddingWorkerApplication,
) -> None:
    session = object()
    dispatch = SimpleNamespace(dispatch_next=AsyncMock(return_value=False))
    monkeypatch.setattr(runtime, "session_factory", lambda: SessionContext(session))
    monkeypatch.setattr(embedding_worker, "RecommendationRepository", Mock(return_value=object()))
    monkeypatch.setattr(embedding_worker, "EmbeddingDispatchService", Mock(return_value=dispatch))
    sleep = AsyncMock(side_effect=asyncio.CancelledError)
    monkeypatch.setattr(embedding_worker.asyncio, "sleep", sleep)

    with pytest.raises(asyncio.CancelledError):
        await runtime.relay_outbox()

    dispatch.dispatch_next.assert_awaited_once()
    sleep.assert_awaited_once_with(0.5)


async def test_relay_outbox_logs_and_retries_failures(
    monkeypatch: pytest.MonkeyPatch,
    runtime: embedding_worker.EmbeddingWorkerApplication,
) -> None:
    class BrokenContext(SessionContext):
        async def __aenter__(self) -> object:
            raise RuntimeError("database unavailable")

    monkeypatch.setattr(runtime, "session_factory", lambda: BrokenContext(object()))
    log = Mock()
    monkeypatch.setattr(embedding_worker.logger, "exception", log)
    sleep = AsyncMock(side_effect=asyncio.CancelledError)
    monkeypatch.setattr(embedding_worker.asyncio, "sleep", sleep)

    with pytest.raises(asyncio.CancelledError):
        await runtime.relay_outbox()

    log.assert_called_once_with("embedding outbox relay failed")
    sleep.assert_awaited_once_with(2)


async def test_worker_lifecycle_starts_and_stops_resources(
    monkeypatch: pytest.MonkeyPatch,
    runtime: embedding_worker.EmbeddingWorkerApplication,
) -> None:
    task = Mock()
    task.cancel = Mock()
    created: list[object] = []

    def create_task(coroutine: object, *, name: str) -> Mock:
        created.append(coroutine)
        assert name == "embedding-outbox-relay"
        coroutine.close()  # type: ignore[attr-defined]
        return task

    gather = AsyncMock()
    llm_client = SimpleNamespace(aclose=AsyncMock())
    engine = SimpleNamespace(dispose=AsyncMock())
    monkeypatch.setattr(embedding_worker.asyncio, "create_task", create_task)
    monkeypatch.setattr(embedding_worker.asyncio, "gather", gather)
    await runtime.llm_client.aclose()
    await runtime.engine.dispose()
    monkeypatch.setattr(runtime, "llm_client", llm_client)
    monkeypatch.setattr(runtime, "engine", engine)
    monkeypatch.setattr(runtime, "relay_task", None)

    await runtime.start_relay()
    await runtime.stop_relay()

    assert len(created) == 1
    task.cancel.assert_called_once_with()
    gather.assert_awaited_once_with(task, return_exceptions=True)
    llm_client.aclose.assert_awaited_once_with()
    engine.dispose.assert_awaited_once_with()


async def test_worker_healthcheck_pings_and_closes_broker(
    monkeypatch: pytest.MonkeyPatch,
    settings: Settings,
) -> None:
    broker = SimpleNamespace(
        connect=AsyncMock(),
        ping=AsyncMock(return_value=True),
        stop=AsyncMock(),
    )
    broker_factory = Mock(return_value=broker)
    monkeypatch.setattr(embedding_worker, "RabbitBroker", broker_factory)

    assert await embedding_worker.rabbitmq_is_healthy(settings)

    broker_factory.assert_called_once_with(settings.rabbitmq_url)
    broker.connect.assert_awaited_once_with()
    broker.ping.assert_awaited_once_with(timeout=2)
    broker.stop.assert_awaited_once_with()


async def test_worker_healthcheck_reports_connection_failure(
    monkeypatch: pytest.MonkeyPatch,
    settings: Settings,
) -> None:
    broker = SimpleNamespace(
        connect=AsyncMock(side_effect=ConnectionError),
        ping=AsyncMock(),
        stop=AsyncMock(),
    )
    monkeypatch.setattr(embedding_worker, "RabbitBroker", Mock(return_value=broker))

    assert not await embedding_worker.rabbitmq_is_healthy(settings)

    broker.ping.assert_not_awaited()
    broker.stop.assert_awaited_once_with()


def test_worker_main_runs_application(monkeypatch: pytest.MonkeyPatch) -> None:
    run = AsyncMock()
    monkeypatch.setattr(embedding_worker, "run", run)
    monkeypatch.setattr(sys, "argv", ["embedding_worker"])

    embedding_worker.main()

    run.assert_awaited_once_with()


@pytest.mark.parametrize(("healthy", "exit_code"), [(True, 0), (False, 1)])
def test_worker_main_healthcheck(
    monkeypatch: pytest.MonkeyPatch,
    healthy: bool,
    exit_code: int,
) -> None:
    healthcheck = AsyncMock(return_value=healthy)
    monkeypatch.setattr(embedding_worker, "rabbitmq_is_healthy", healthcheck)
    monkeypatch.setattr(sys, "argv", ["embedding_worker", "healthcheck"])

    with pytest.raises(SystemExit) as error:
        embedding_worker.main()

    assert error.value.code == exit_code
    healthcheck.assert_awaited_once_with()


def test_worker_main_rejects_unknown_command(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["embedding_worker", "unknown"])

    with pytest.raises(SystemExit, match=r"usage: python -m tramplin\.embedding_worker"):
        embedding_worker.main()
