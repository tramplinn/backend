from collections.abc import MutableMapping, Sequence
from typing import Any, cast
from unittest.mock import AsyncMock

import aiormq.exceptions
import pytest
from faststream.asgi import HttpHandler
from faststream.asgi.types import Scope

from tramplin.infrastructure import health
from tramplin.infrastructure.health import (
    CONNECTED_WAIT_SECONDS,
    LIVE_PATH,
    READY_PATH,
    health_routes,
    readiness_route,
)


def scope() -> Scope:
    return {
        "type": "http",
        "method": "GET",
        "scheme": "http",
        "path": "/",
        "root_path": "",
        "headers": [],
        "query_string": b"",
    }


async def response_status(handler: HttpHandler) -> int:
    collected: list[MutableMapping[str, Any]] = []

    async def receive() -> dict[str, str]:
        return {"type": "http.disconnect"}

    async def send(message: MutableMapping[str, Any]) -> None:
        collected.append(message)

    await handler(scope(), receive, send)
    return cast(int, collected[0]["status"])


def connected_broker() -> AsyncMock:
    broker = AsyncMock()
    broker.ping = AsyncMock(return_value=True)
    return broker


def broken_broker() -> AsyncMock:
    broker = AsyncMock()
    broker.ping = AsyncMock(return_value=False)
    return broker


async def test_liveness_answers_200() -> None:
    assert await response_status(health.liveness) == 200


async def test_readiness_answers_204_when_broker_connected() -> None:
    broker = connected_broker()

    assert await response_status(readiness_route(cast(Any, broker))) == 204
    broker.ping.assert_awaited_once_with(CONNECTED_WAIT_SECONDS)


async def test_readiness_answers_500_when_broker_disconnected() -> None:
    broker = broken_broker()

    assert await response_status(readiness_route(cast(Any, broker))) == 500
    broker.ping.assert_awaited_once_with(CONNECTED_WAIT_SECONDS)


async def test_health_routes_serve_live_and_ready_pairs() -> None:
    routes = dict(health_routes(cast(Any, connected_broker())))

    assert list(routes) == [LIVE_PATH, READY_PATH]
    assert await response_status(routes[LIVE_PATH]) == 200
    assert await response_status(routes[READY_PATH]) == 204


def test_readiness_route_requires_broker() -> None:
    route = readiness_route(cast(Any, connected_broker()))

    assert isinstance(route, HttpHandler)


class _FakeAsgiApp:
    """Ловит то, что serve() отдаёт в uvicorn через run_extra_options."""

    def __init__(self) -> None:
        self.routes: Sequence[tuple[str, Any]] = ()
        self.options: dict[str, Any] = {}

    async def run(self, run_extra_options: dict[str, Any] | None = None) -> None:
        self.options = dict(run_extra_options or {})


class _FakeFastStream:
    def __init__(self) -> None:
        self.asgi: _FakeAsgiApp | None = None

    def as_asgi(self, asgi_routes: Sequence[tuple[str, Any]]) -> _FakeAsgiApp:
        self.asgi = _FakeAsgiApp()
        self.asgi.routes = asgi_routes
        return self.asgi


class _ScriptedBroker:
    """Брокер, у которого connect() разыгрывает заранее заготовленный сценарий."""

    def __init__(self, script: list[BaseException | None]) -> None:
        self.script = script
        self.calls = 0

    async def connect(self) -> None:
        self.calls += 1
        outcome = self.script[min(self.calls, len(self.script)) - 1]
        if outcome is not None:
            raise outcome


async def test_serve_passes_cli_style_uvicorn_options() -> None:
    # run_extra_options приводится как параметры CLI uvicorn: access_log — строка,
    # bool здесь уронит запуск воркера (cast_uvicorn_params зовёт .lower()).
    expected = _FakeFastStream()
    broker = connected_broker()

    await health.serve(cast(Any, expected), cast(Any, broker), port=9876)

    assert expected.asgi is not None
    assert [path for path, _ in expected.asgi.routes] == [LIVE_PATH, READY_PATH]
    assert expected.asgi.options["host"] == health.BIND_HOST
    assert expected.asgi.options["port"] == 9876
    assert expected.asgi.options["access_log"] == "false"
    broker.connect.assert_awaited_once()


async def test_connect_with_retries_waits_out_network_outage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(health, "CONNECT_RETRY_SECONDS", 0.0)
    refused = ConnectionRefusedError("rabbit временно недоступен")
    broker = _ScriptedBroker([refused, refused, None])

    await health._connect_with_retries(cast(Any, broker))

    assert broker.calls == 3


async def test_connect_with_retries_fails_fast_on_bad_credentials() -> None:
    broker = _ScriptedBroker([aiormq.ProbableAuthenticationError("ACCESS_REFUSED")])

    with pytest.raises(aiormq.ProbableAuthenticationError):
        await health._connect_with_retries(cast(Any, broker))

    assert broker.calls == 1
