import asyncio as asyncio
import logging
from typing import Any

import httpx
import uuid_utils.compat as uuid
from faststream import AckPolicy, FastStream
from faststream.rabbit import QueueType, RabbitBroker, RabbitMessage, RabbitQueue
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tramplin.core.config import load_settings
from tramplin.infrastructure.algorithm_queue import FastStreamSubmissionQueue
from tramplin.infrastructure.judge0 import Judge0CodeRunner
from tramplin.infrastructure.repositories.algorithms import AlgorithmRepository
from tramplin.services.algorithms import AlgorithmDispatchService, AlgorithmWorkerService

logger = logging.getLogger(__name__)
settings = load_settings()
engine = create_async_engine(settings.database_url, pool_pre_ping=True)
session_factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
broker = RabbitBroker(settings.rabbitmq_url)
job_queue = RabbitQueue(
    settings.algorithm_queue_name,
    queue_type=QueueType.QUORUM,
    durable=True,
)
submission_queue = FastStreamSubmissionQueue(broker, job_queue)
app = FastStream(broker)
relay_task: asyncio.Task[None] | None = None
runner_client = httpx.AsyncClient(timeout=settings.http_timeout.total_seconds())
runner = Judge0CodeRunner(runner_client, settings)


class AlgorithmJobMessage(BaseModel):
    submission_id: uuid.UUID


@broker.subscriber(job_queue, ack_policy=AckPolicy.NACK_ON_ERROR)
async def execute_submission(message: AlgorithmJobMessage, raw: RabbitMessage) -> None:
    async with session_factory() as session:
        service = AlgorithmWorkerService(
            session,
            AlgorithmRepository(session),
            runner,
            settings,
        )
        await service.process(
            message.submission_id,
            redelivered=bool(raw.raw_message.redelivered),
        )


async def relay_outbox() -> None:
    """Publish committed DB jobs; duplicates after a crash are intentionally harmless."""
    while True:
        try:
            async with session_factory() as session:
                dispatched = await AlgorithmDispatchService(
                    session,
                    AlgorithmRepository(session),
                    submission_queue,
                ).dispatch_next()
            if not dispatched:
                await asyncio.sleep(0.5)
        except Exception:
            logger.exception("algorithm outbox relay failed")
            await asyncio.sleep(2)


@app.after_startup
async def start_relay(**_: Any) -> None:
    global relay_task
    relay_task = asyncio.create_task(relay_outbox(), name="algorithm-outbox-relay")


@app.on_shutdown
async def stop_relay(**_: Any) -> None:
    if relay_task is not None:
        relay_task.cancel()
        await asyncio.gather(relay_task, return_exceptions=True)
    await runner_client.aclose()
    await engine.dispose()
