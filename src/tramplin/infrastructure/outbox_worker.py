import asyncio
import logging
import sys
from collections.abc import Awaitable, Callable

from faststream.rabbit import RabbitBroker
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from tramplin.core.config import Settings, load_settings


def build_engine_and_sessionmaker(
    settings: Settings,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    return engine, session_factory


async def relay_outbox_loop(
    dispatch_once: Callable[[], Awaitable[bool]],
    *,
    logger: logging.Logger,
    failure_label: str,
) -> None:
    """Publish committed DB jobs; duplicates after a crash are intentionally harmless."""
    while True:
        try:
            dispatched = await dispatch_once()
            if not dispatched:
                await asyncio.sleep(0.5)
        except Exception:
            logger.exception(failure_label)
            await asyncio.sleep(2)


async def cancel_and_await(task: asyncio.Task[None] | None) -> None:
    if task is not None:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def rabbitmq_is_healthy(
    settings: Settings | None,
    broker_factory: Callable[[str], RabbitBroker],
) -> bool:
    settings = settings or load_settings()
    broker = broker_factory(settings.rabbitmq_url)
    try:
        await asyncio.wait_for(broker.connect(), timeout=3)
        return await broker.ping(timeout=2)
    except Exception:
        return False
    finally:
        await broker.stop()


def run_cli(
    run: Callable[[], Awaitable[None]],
    healthcheck: Callable[[], Awaitable[bool]],
    *,
    usage: str,
) -> None:
    if not sys.argv[1:]:
        asyncio.run(run())
        return
    if sys.argv[1:] == ["healthcheck"]:
        raise SystemExit(0 if asyncio.run(healthcheck()) else 1)
    raise SystemExit(usage)
