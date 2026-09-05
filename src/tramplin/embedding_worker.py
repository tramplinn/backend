import asyncio as asyncio
import logging
from typing import Any

import uuid_utils.compat as uuid
from faststream import AckPolicy, FastStream
from faststream.rabbit import QueueType, RabbitBroker, RabbitQueue
from pydantic import BaseModel

from tramplin.core.config import Settings, load_settings
from tramplin.infrastructure.embedding_queue import FastStreamEmbeddingQueue
from tramplin.infrastructure.llm import LlmClient
from tramplin.infrastructure.outbox_worker import (
    build_engine_and_sessionmaker,
    cancel_and_await,
    relay_outbox_loop,
    run_cli,
)
from tramplin.infrastructure.outbox_worker import rabbitmq_is_healthy as _rabbitmq_is_healthy
from tramplin.infrastructure.repositories.recommendations import RecommendationRepository
from tramplin.models.enums import RecommendationEntityType
from tramplin.services.recommendations import EmbeddingDispatchService, EmbeddingWorkerService

logger = logging.getLogger(__name__)


class EmbeddingJobMessage(BaseModel):
    entity_type: RecommendationEntityType
    entity_id: uuid.UUID


class EmbeddingWorkerApplication:
    """Отдельный процесс: считает эмбеддинги курсов/алгоритмов через OpenAI,
    независимо от джаджа алгоритмов — разная нагрузка, разный внешний сервис."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.engine, self.session_factory = build_engine_and_sessionmaker(settings)
        self.broker = RabbitBroker(settings.rabbitmq_url)
        self.job_queue = RabbitQueue(
            settings.embedding_queue_name,
            queue_type=QueueType.QUORUM,
            durable=True,
        )
        self.embedding_queue = FastStreamEmbeddingQueue(self.broker, self.job_queue)
        self.llm_client = LlmClient(settings)
        self.relay_task: asyncio.Task[None] | None = None
        self.app = FastStream(self.broker)

        self.broker.subscriber(
            self.job_queue,
            ack_policy=AckPolicy.NACK_ON_ERROR,
        )(self.execute_embedding_job)
        self.app.after_startup(self.start_relay)
        self.app.on_shutdown(self.stop_relay)

    async def execute_embedding_job(self, message: EmbeddingJobMessage) -> None:
        async with self.session_factory() as session:
            service = EmbeddingWorkerService(
                session,
                RecommendationRepository(session),
                self.llm_client,
            )
            await service.process(message.entity_type, message.entity_id)

    async def relay_outbox(self) -> None:
        async def dispatch_once() -> bool:
            async with self.session_factory() as session:
                return await EmbeddingDispatchService(
                    session,
                    RecommendationRepository(session),
                    self.embedding_queue,
                ).dispatch_next()

        await relay_outbox_loop(
            dispatch_once,
            logger=logger,
            failure_label="embedding outbox relay failed",
        )

    async def start_relay(self, **_: Any) -> None:
        self.relay_task = asyncio.create_task(
            self.relay_outbox(),
            name="embedding-outbox-relay",
        )

    async def stop_relay(self, **_: Any) -> None:
        await cancel_and_await(self.relay_task)
        await self.llm_client.aclose()
        await self.engine.dispose()


def create_worker(settings: Settings | None = None) -> EmbeddingWorkerApplication:
    return EmbeddingWorkerApplication(settings or load_settings())


async def run() -> None:
    await create_worker().app.run()


async def rabbitmq_is_healthy(settings: Settings | None = None) -> bool:
    return await _rabbitmq_is_healthy(settings, RabbitBroker)


def main() -> None:
    run_cli(
        run,
        rabbitmq_is_healthy,
        usage="usage: python -m tramplin.embedding_worker [healthcheck]",
    )


if __name__ == "__main__":
    main()
