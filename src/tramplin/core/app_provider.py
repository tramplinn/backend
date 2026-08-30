from collections.abc import AsyncIterator

import aioboto3
import httpx
from dishka import Provider, Scope, from_context, provide
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from tramplin.core.config import Settings
from tramplin.core.security import AccessTokenCodec
from tramplin.infrastructure.github import GitHubOAuthClient
from tramplin.infrastructure.llm import LlmClient
from tramplin.infrastructure.oauth_state import OAuthStateStore
from tramplin.infrastructure.s3_storage import S3Storage
from tramplin.infrastructure.tutor_quota import TutorQuota


class AppProvider(Provider):
    scope = Scope.APP

    settings = from_context(provides=Settings)

    @provide
    async def engine(self, settings: Settings) -> AsyncIterator[AsyncEngine]:
        engine = create_async_engine(settings.database_url, pool_pre_ping=True)
        yield engine
        await engine.dispose()

    @provide
    def session_factory(self, engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
        return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)

    @provide
    async def redis(self, settings: Settings) -> AsyncIterator[Redis]:
        client = Redis.from_url(settings.redis_url, decode_responses=True)
        yield client
        await client.aclose()

    @provide
    async def http_client(self, settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
        async with httpx.AsyncClient(timeout=settings.http_timeout.total_seconds()) as client:
            yield client

    @provide
    def token_codec(self, settings: Settings) -> AccessTokenCodec:
        return AccessTokenCodec(settings)

    @provide
    def oauth_state_store(self, redis: Redis, settings: Settings) -> OAuthStateStore:
        return OAuthStateStore(redis, settings)

    @provide
    def tutor_quota(self, redis: Redis, settings: Settings) -> TutorQuota:
        return TutorQuota(redis, settings)

    # APP-скоуп обязателен: поток ответа модели живёт дольше HTTP-запроса.
    @provide
    async def llm_client(self, settings: Settings) -> AsyncIterator[LlmClient]:
        client = LlmClient(settings)
        yield client
        await client.aclose()

    @provide
    def github_client(
        self,
        settings: Settings,
        client: httpx.AsyncClient,
    ) -> GitHubOAuthClient:
        return GitHubOAuthClient(settings, client)

    @provide
    async def storage(self, settings: Settings) -> AsyncIterator[S3Storage]:
        session = aioboto3.Session(
            aws_access_key_id=settings.s3_access_key.get_secret_value(),
            aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
            region_name=settings.s3_region,
        )
        async with session.client("s3", endpoint_url=settings.s3_endpoint_url) as client:
            yield S3Storage(client, settings.s3_bucket, settings.s3_public_base_url)
