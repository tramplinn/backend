import asyncio as asyncio
import logging
import sys
from typing import Any

import httpx
import uuid_utils.compat as uuid
from faststream import AckPolicy, FastStream
from faststream.rabbit import QueueType, RabbitBroker, RabbitMessage, RabbitQueue
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from tramplin.core.config import Settings, load_settings
from tramplin.infrastructure.algorithm_queue import FastStreamSubmissionQueue
from tramplin.infrastructure.judge0 import Judge0CodeRunner
from tramplin.infrastructure.repositories.algorithms import AlgorithmRepository
from tramplin.services.algorithms import AlgorithmDispatchService, AlgorithmWorkerService

logger = logging.getLogger(__name__)


class AlgorithmJobMessage(BaseModel):
    submission_id: uuid.UUID


class AlgorithmWorkerApplication:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.engine: AsyncEngine = create_async_engine(settings.database_url, pool_pre_ping=True)
        self.session_factory = async_sessionmaker(
            self.engine,
            expire_on_commit=False,
            autoflush=False,
        )
        self.broker = RabbitBroker(settings.rabbitmq_url)
        self.job_queue = RabbitQueue(
            settings.algorithm_queue_name,
            queue_type=QueueType.QUORUM,
            durable=True,
        )
        self.submission_queue = FastStreamSubmissionQueue(self.broker, self.job_queue)
        self.runner_client = httpx.AsyncClient(timeout=settings.http_timeout.total_seconds())
        self.runner = Judge0CodeRunner(self.runner_client, settings)
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
        """Publish committed DB jobs; duplicates after a crash are intentionally harmless."""
        while True:
            try:
                async with self.session_factory() as session:
                    dispatched = await AlgorithmDispatchService(
                        session,
                        AlgorithmRepository(session),
                        self.submission_queue,
                    ).dispatch_next()
                if not dispatched:
                    await asyncio.sleep(0.5)
            except Exception:
                logger.exception("algorithm outbox relay failed")
                await asyncio.sleep(2)

    async def start_relay(self, **_: Any) -> None:
        self.relay_task = asyncio.create_task(
            self.relay_outbox(),
            name="algorithm-outbox-relay",
        )

    async def stop_relay(self, **_: Any) -> None:
        if self.relay_task is not None:
            self.relay_task.cancel()
            await asyncio.gather(self.relay_task, return_exceptions=True)
        await self.runner_client.aclose()
        await self.engine.dispose()


def create_worker(settings: Settings | None = None) -> AlgorithmWorkerApplication:
    return AlgorithmWorkerApplication(settings or load_settings())


async def run() -> None:
    await create_worker().app.run()


async def rabbitmq_is_healthy(settings: Settings | None = None) -> bool:
    settings = settings or load_settings()
    broker = RabbitBroker(settings.rabbitmq_url)
    try:
        return await broker.ping(timeout=2)
    finally:
        await broker.stop()


def main() -> None:
    if not sys.argv[1:]:
        asyncio.run(run())
        return
    if sys.argv[1:] == ["healthcheck"]:
        raise SystemExit(0 if asyncio.run(rabbitmq_is_healthy()) else 1)
    raise SystemExit("usage: python -m tramplin.worker [healthcheck]")


if __name__ == "__main__":
    main()
