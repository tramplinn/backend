import asyncio as asyncio
import logging
from typing import Any

import httpx
import uuid_utils.compat as uuid
from faststream import AckPolicy, FastStream
from faststream.rabbit import QueueType, RabbitBroker, RabbitMessage, RabbitQueue
from pydantic import BaseModel

from tramplin.core.config import Settings, load_settings
from tramplin.infrastructure.algorithm_queue import FastStreamSubmissionQueue
from tramplin.infrastructure.outbox_worker import (
    build_engine_and_sessionmaker,
    cancel_and_await,
    relay_outbox_loop,
    run_cli,
)
from tramplin.infrastructure.outbox_worker import rabbitmq_is_healthy as _rabbitmq_is_healthy
from tramplin.infrastructure.piston import PistonCodeRunner
from tramplin.infrastructure.repositories.algorithms import AlgorithmRepository
from tramplin.services.algorithms import AlgorithmDispatchService, AlgorithmWorkerService

logger = logging.getLogger(__name__)


class AlgorithmJobMessage(BaseModel):
    submission_id: uuid.UUID


class AlgorithmWorkerApplication:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.engine, self.session_factory = build_engine_and_sessionmaker(settings)
        self.broker = RabbitBroker(settings.rabbitmq_url)
        # declare=False: топология — в infra/rabbitmq/definitions.json, не здесь.
        # Отсутствующая очередь — явная ошибка на старте, а не молчаливое создание.
        self.job_queue = RabbitQueue(
            settings.algorithm_queue_name,
            queue_type=QueueType.QUORUM,
            durable=True,
            declare=False,
        )
        self.submission_queue = FastStreamSubmissionQueue(self.broker, self.job_queue)
        self.runner_client = httpx.AsyncClient(timeout=settings.http_timeout.total_seconds())
        self.runner = PistonCodeRunner(self.runner_client, settings)
        self.relay_task: asyncio.Task[None] | None = None
        self.app = FastStream(self.broker)

        self.broker.subscriber(
            self.job_queue,
            ack_policy=AckPolicy.NACK_ON_ERROR,
        )(self.execute_submission)
        self.app.after_startup(self.start_relay)
        self.app.on_shutdown(self.stop_relay)

    async def execute_submission(
        self,
        message: AlgorithmJobMessage,
        raw: RabbitMessage,
    ) -> None:
        async with self.session_factory() as session:
            service = AlgorithmWorkerService(
                session,
                AlgorithmRepository(session),
                self.runner,
                self.settings,
            )
            await service.process(
                message.submission_id,
                redelivered=bool(raw.raw_message.redelivered),
            )

    async def relay_outbox(self) -> None:
        async def dispatch_once() -> bool:
            async with self.session_factory() as session:
                return await AlgorithmDispatchService(
                    session,
                    AlgorithmRepository(session),
                    self.submission_queue,
                ).dispatch_next()

        await relay_outbox_loop(
            dispatch_once,
            logger=logger,
            failure_label="algorithm outbox relay failed",
        )

    async def start_relay(self, **_: Any) -> None:
        self.relay_task = asyncio.create_task(
            self.relay_outbox(),
            name="algorithm-outbox-relay",
        )

    async def stop_relay(self, **_: Any) -> None:
        await cancel_and_await(self.relay_task)
        await self.runner_client.aclose()
        await self.engine.dispose()


def create_worker(settings: Settings | None = None) -> AlgorithmWorkerApplication:
    return AlgorithmWorkerApplication(settings or load_settings())


async def run() -> None:
    await create_worker().app.run()


async def rabbitmq_is_healthy(settings: Settings | None = None) -> bool:
    return await _rabbitmq_is_healthy(settings, RabbitBroker)


def main() -> None:
    run_cli(
        run,
        rabbitmq_is_healthy,
        usage="usage: python -m tramplin.algo_worker [healthcheck]",
    )


if __name__ == "__main__":
    main()
