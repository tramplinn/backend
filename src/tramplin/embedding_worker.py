import asyncio as asyncio
import logging
import sys
from typing import Any

import uuid_utils.compat as uuid
from faststream import AckPolicy, FastStream
from faststream.rabbit import QueueType, RabbitBroker, RabbitQueue
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from tramplin.core.config import Settings, load_settings
from tramplin.infrastructure.embedding_queue import FastStreamEmbeddingQueue
from tramplin.infrastructure.llm import LlmClient
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
        self.engine: AsyncEngine = create_async_engine(settings.database_url, pool_pre_ping=True)
        self.session_factory = async_sessionmaker(
            self.engine,
            expire_on_commit=False,
            autoflush=False,
        )
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
        """Publish committed DB jobs; duplicates after a crash are intentionally harmless."""
        while True:
            try:
                async with self.session_factory() as session:
                    dispatched = await EmbeddingDispatchService(
                        session,
                        RecommendationRepository(session),
                        self.embedding_queue,
                    ).dispatch_next()
                if not dispatched:
                    await asyncio.sleep(0.5)
            except Exception:
                logger.exception("embedding outbox relay failed")
                await asyncio.sleep(2)

    async def start_relay(self, **_: Any) -> None:
        self.relay_task = asyncio.create_task(
            self.relay_outbox(),
            name="embedding-outbox-relay",
        )

    async def stop_relay(self, **_: Any) -> None:
        if self.relay_task is not None:
            self.relay_task.cancel()
            await asyncio.gather(self.relay_task, return_exceptions=True)
        await self.llm_client.aclose()
        await self.engine.dispose()


def create_worker(settings: Settings | None = None) -> EmbeddingWorkerApplication:
    return EmbeddingWorkerApplication(settings or load_settings())


async def run() -> None:
    await create_worker().app.run()


async def rabbitmq_is_healthy(settings: Settings | None = None) -> bool:
    settings = settings or load_settings()
    broker = RabbitBroker(settings.rabbitmq_url)
    try:
        await asyncio.wait_for(broker.connect(), timeout=3)
        return await broker.ping(timeout=2)
    except Exception:
        return False
    finally:
        await broker.stop()


def main() -> None:
    if not sys.argv[1:]:
        asyncio.run(run())
        return
    if sys.argv[1:] == ["healthcheck"]:
        raise SystemExit(0 if asyncio.run(rabbitmq_is_healthy()) else 1)
    raise SystemExit("usage: python -m tramplin.embedding_worker [healthcheck]")


if __name__ == "__main__":
    main()
