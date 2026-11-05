"""Ручки здоровья воркеров: /health/live и /health/ready вместо exec-проб.

exec-проба при каждом прогоне заново импортировала весь стек, жила ~5 секунд
чистого CPU и всё это время держала timeout 5s под угрозой — ради состояния,
которое уже есть в памяти: брокер сам знает, установлено его соединение или нет.
Здесь воркер поднимается как ASGI (AsgiFastStream внутри uvicorn — тот же
процесс и событийный цикл, что у брокера) и отдаёт:

- /health/live — событийный цикл отвечает HTTP, значит процесс жив;
- /health/ready — собственное соединение воркера с брокером установлено.

Если соединение разорвалось, FastStream переустанавливает его сам: readiness
вернётся без перезапуска пода, а liveness на состояние сети не завязан.

Первое соединение с брокером — исключение из этого правила: `broker.connect()`
одноразовый, сетевой отказ поднимет ошибку ещё до ASGI-старта, и uvicorn
останется жить без брокера (readiness навсегда 500). Поэтому serve() сам
дотягивает первый коннект с ретраями; неверные креды не ретраятся — это
ошибка конфигурации, а не сети.
"""

import asyncio
import logging
from collections.abc import Sequence
from typing import Final

from aiormq.exceptions import ProbableAuthenticationError
from faststream import FastStream
from faststream.asgi import AsgiResponse, HttpHandler, get, make_ping_asgi
from faststream.asgi.types import Scope
from faststream.rabbit import RabbitBroker

logger = logging.getLogger(__name__)

LIVE_PATH: Final = "/health/live"
READY_PATH: Final = "/health/ready"

# kubelet ходит на pod IP, а не в localhost пода — слушать нужно все интерфейсы.
# S104: назначение 0.0.0.0 оправдано, порт не публикуется наружу (нет Service).
BIND_HOST: Final = "0.0.0.0"  # noqa: S104

# Столько readiness-ручка может ждать события connected, прежде чем ответить 500;
# timeoutSeconds пробы в k8s/workers.yaml берёт запас поверх этого потолка.
CONNECTED_WAIT_SECONDS: Final = 2.0

# Пауза между попытками первого соединения; ограничение сверху делает k8s
# startupProbe на /health/live: не подключились за отведённое окно — pod рестартуют.
CONNECT_RETRY_SECONDS: Final = 5.0


@get(include_in_schema=False, description="Процесс жив: событийный цикл отвечает.")
async def liveness(_scope: Scope) -> AsgiResponse:
    return AsgiResponse(b"", 200)


def readiness_route(broker: RabbitBroker) -> HttpHandler:
    """204, пока соединение воркера с брокером не потеряно; 500 — в противном случае."""
    return make_ping_asgi(broker, timeout=CONNECTED_WAIT_SECONDS, include_in_schema=False)


def health_routes(broker: RabbitBroker) -> Sequence[tuple[str, HttpHandler]]:
    """Маршруты для `FastStream(...).as_asgi(asgi_routes=...)` каждого воркера."""
    return (
        (LIVE_PATH, liveness),
        (READY_PATH, readiness_route(broker)),
    )


async def _connect_with_retries(broker: RabbitBroker) -> None:
    """Первое соединение с брокером: сетевые сбои ретраим, конфигурационные — нет.

    RabbitBroker.connect() одноразовый: отказ на первой попытке FastStream не
    ретраит и просто оставляет uvicorn жить без брокера — readiness такими
    воркерами определяется навсегда 500. Поэтому здесь своя петля: ошибки сети
    считаем транзиентными, а неверный логин/пароль/vhost — ошибкой конфигурации,
    которую надо поднять наверх, а не прятать ретраями.
    """
    while True:
        try:
            await broker.connect()
            return
        except ProbableAuthenticationError:
            logger.error("RabbitMQ: неверные креды или vhost, дальше не ретраим")
            raise
        except (TimeoutError, OSError) as exc:
            logger.warning(
                "RabbitMQ пока недоступен: %s — повторная попытка через %s с",
                exc,
                CONNECT_RETRY_SECONDS,
            )
            await asyncio.sleep(CONNECT_RETRY_SECONDS)


async def serve(app: FastStream, broker: RabbitBroker, *, port: int) -> None:
    """Поднимает воркера: uvicorn в том же процессе обслуживает брокера и ручки здоровья.

    uvicorn перехватывает сигналы сам, поэтому graceful shutdown доезжает
    до FastStream через ASGI lifespan.
    """
    await _connect_with_retries(broker)
    await app.as_asgi(asgi_routes=health_routes(broker)).run(
        run_extra_options={
            "host": BIND_HOST,
            "port": port,
            # Проба ходит каждые 10 секунд — доступный лог о ней шум, а не сигнал.
            # Строка, не bool: run_extra_options приводит параметры как в CLI uvicorn.
            "access_log": "false",
        },
    )
