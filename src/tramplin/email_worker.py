import asyncio
import logging
from typing import Any

from faststream import FastStream
from faststream.rabbit import QueueType, RabbitBroker, RabbitQueue

from tramplin.core.config import Settings, load_settings
from tramplin.infrastructure.email_queue import FastStreamEmailQueue
from tramplin.infrastructure.outbox_worker import (
    build_engine_and_sessionmaker,
    cancel_and_await,
    relay_outbox_loop,
    run_cli,
)
from tramplin.infrastructure.outbox_worker import rabbitmq_is_healthy as _rabbitmq_is_healthy
from tramplin.infrastructure.repositories.notifications import EmailJobRepository
from tramplin.services.notifications import EmailDispatchService

logger = logging.getLogger(__name__)


class EmailWorkerApplication:
    """Только релей outbox → RabbitMQ: доставку писем делает независимый
    email-service, у которого нет ни БД, ни знания о шаблонах."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.engine, self.session_factory = build_engine_and_sessionmaker(settings)
        self.broker = RabbitBroker(settings.rabbitmq_url)
        # declare=False: топология — в infra/rabbitmq/definitions.json, не здесь.
        self.email_queue = FastStreamEmailQueue(
            self.broker,
            RabbitQueue(
                settings.email_transactional_queue_name,
                queue_type=QueueType.QUORUM,
                durable=True,
                declare=False,
            ),
            RabbitQueue(
                settings.email_bulk_queue_name,
                queue_type=QueueType.QUORUM,
                durable=True,
                declare=False,
            ),
        )
        self.relay_task: asyncio.Task[None] | None = None
        self.app = FastStream(self.broker)

        self.app.after_startup(self.start_relay)
        self.app.on_shutdown(self.stop_relay)

    async def relay_outbox(self) -> None:
        async def dispatch_once() -> bool:
            async with self.session_factory() as session:
                return await EmailDispatchService(
                    session,
                    EmailJobRepository(session),
                    self.email_queue,
                ).dispatch_next()

        await relay_outbox_loop(
            dispatch_once,
            logger=logger,
            failure_label="email outbox relay failed",
        )

    async def start_relay(self, **_: Any) -> None:
        self.relay_task = asyncio.create_task(self.relay_outbox(), name="email-outbox-relay")

    async def stop_relay(self, **_: Any) -> None:
        await cancel_and_await(self.relay_task)
        await self.engine.dispose()


def create_worker(settings: Settings | None = None) -> EmailWorkerApplication:
    return EmailWorkerApplication(settings or load_settings())


async def run() -> None:
    await create_worker().app.run()


async def rabbitmq_is_healthy(settings: Settings | None = None) -> bool:
    return await _rabbitmq_is_healthy(settings, RabbitBroker)


def main() -> None:
    run_cli(
        run,
        rabbitmq_is_healthy,
        usage="usage: python -m tramplin.email_worker [healthcheck]",
    )


if __name__ == "__main__":
    main()
