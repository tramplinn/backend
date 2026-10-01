"""Интеграционные тесты: настоящий FastAPI-стек поверх настоящей Postgres.

БД берётся из TEST_DATABASE_URL (CI-сервис), иначе поднимается контейнер
pgvector через testcontainers. Схема накатывается alembic-миграциями один раз
за сессию, между тестами все таблицы очищаются TRUNCATE.

Внешние сети (Redis, S3, Piston, LLM, OAuth-провайдеры) подменены фейками
через dishka-провайдер с override=True, остальное — продовый граф зависимостей.
"""

import os
import re
import shutil
import subprocess
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import httpx
import pytest
import uuid_utils.compat as uuid
from alembic import command
from alembic.config import Config
from dishka import AsyncContainer, Provider, Scope, make_async_container, provide
from fakeredis import FakeAsyncRedis
from fastapi import FastAPI
from fastapi.routing import APIRoute
from pydantic import SecretStr
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from starlette.types import ASGIApp, Receive, Send
from starlette.types import Scope as AsgiScope
from testcontainers.community.postgres import PostgresContainer

import tramplin.main
from tests.integration.fakes import Fakes
from tramplin.core.app_provider import AppProvider
from tramplin.core.config import API_PREFIX, Settings
from tramplin.core.request_provider import RequestProvider
from tramplin.core.security import AccessTokenCodec
from tramplin.infrastructure.github import GitHubOAuthClient
from tramplin.infrastructure.gitlab import GitLabOAuthClient
from tramplin.infrastructure.llm import LlmClient
from tramplin.infrastructure.s3_storage import S3Storage
from tramplin.infrastructure.yandex import YandexOAuthClient
from tramplin.main import create_app
from tramplin.models.enums import IdentityProvider, UserRole
from tramplin.models.users import User, UserIdentity
from tramplin.services.contracts import CodeRunner

BACKEND_DIR = Path(__file__).resolve().parents[2]
POSTGRES_IMAGE = "pgvector/pgvector:pg18"
INTEGRATION_DIR = Path(__file__).resolve().parent

# (METHOD, шаблон пути без API_PREFIX) ручек, до которых дошёл хоть один тест.
HIT_ROUTES: set[tuple[str, str]] = set()
_ALL_ROUTES: set[tuple[str, str]] = set()


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if INTEGRATION_DIR in Path(str(item.path)).parents:
            item.add_marker(pytest.mark.integration)


def _docker_host() -> str | None:
    """Docker Desktop на Linux не создаёт /var/run/docker.sock — берём сокет из контекста."""
    if os.environ.get("DOCKER_HOST") or Path("/var/run/docker.sock").exists():
        return os.environ.get("DOCKER_HOST")
    if shutil.which("docker") is None:
        return None
    result = subprocess.run(
        ["docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )
    host = result.stdout.strip()
    return host or None


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    if url := os.environ.get("TEST_DATABASE_URL"):
        yield url
        return

    with pytest.MonkeyPatch.context() as mp:
        if host := _docker_host():
            mp.setenv("DOCKER_HOST", host)
        # Ryuk монтирует docker.sock, которого у Docker Desktop нет; контейнер
        # всё равно останавливается в конце сессии контекстным менеджером.
        mp.setenv(
            "TESTCONTAINERS_RYUK_DISABLED", os.environ.get("TESTCONTAINERS_RYUK_DISABLED", "true")
        )
        # Без Docker тесты падают, а не пропускаются: чинить надо окружение.
        container = PostgresContainer(POSTGRES_IMAGE, driver="asyncpg")
        container.start()
        try:
            yield container.get_connection_url()
        finally:
            container.stop()


@pytest.fixture(scope="session")
def migrated_database_url(database_url: str) -> str:
    # Конфиг без ini-файла: env.py вызывает fileConfig только при наличии файла,
    # а fileConfig отключил бы уже созданные логгеры приложения (и caplog в юнитах).
    config = Config()
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("DATABASE_URL", database_url)
        command.upgrade(config, "head")
    return database_url


@pytest.fixture
async def db(migrated_database_url: str) -> AsyncIterator[AsyncEngine]:
    """Движок для подготовки данных и проверок напрямую в БД; база чистая перед тестом."""
    engine = create_async_engine(migrated_database_url)
    async with engine.begin() as conn:
        tables = (
            await conn.execute(
                text(
                    "SELECT tablename FROM pg_tables "
                    "WHERE schemaname = 'public' AND tablename <> 'alembic_version'"
                )
            )
        ).scalars()
        names = ", ".join(f'"{name}"' for name in tables)
        if names:
            await conn.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
    yield engine
    await engine.dispose()


@pytest.fixture
def integration_settings(migrated_database_url: str) -> Settings:
    return Settings(
        _env_file=None,
        database_url=migrated_database_url,
        jwt_secret=SecretStr("integration-secret-at-least-32-bytes"),
        github_client_id="gh-id",
        github_client_secret=SecretStr("gh-secret"),
        yandex_client_id="ya-id",
        yandex_client_secret=SecretStr("ya-secret"),
        gitlab_client_id="gl-id",
        gitlab_client_secret=SecretStr("gl-secret"),
        mcp_oauth_client_secret=SecretStr("mcp-client-secret"),
        llm_model="test-model",
        llm_api_key=SecretStr("test-llm-key"),
    )


@pytest.fixture
def fakes() -> Fakes:
    return Fakes()


@pytest.fixture
async def redis() -> AsyncIterator[Redis]:
    client = FakeAsyncRedis(decode_responses=True)
    yield client
    await client.aclose()


class FakeInfraProvider(Provider):
    scope = Scope.APP

    def __init__(self, fakes: Fakes, redis: Redis) -> None:
        super().__init__()
        self._fakes = fakes
        self._redis = redis

    @provide(override=True)
    def redis(self) -> Redis:
        return self._redis

    @provide(override=True)
    def storage(self) -> S3Storage:
        return cast(S3Storage, self._fakes.storage)

    @provide(override=True)
    def code_runner(self) -> CodeRunner:
        return self._fakes.runner

    @provide(override=True)
    def llm_client(self) -> LlmClient:
        return cast(LlmClient, self._fakes.llm)

    @provide(override=True)
    def github_client(self) -> GitHubOAuthClient:
        return cast(GitHubOAuthClient, self._fakes.github)

    @provide(override=True)
    def yandex_client(self) -> YandexOAuthClient:
        return cast(YandexOAuthClient, self._fakes.yandex)

    @provide(override=True)
    def gitlab_client(self) -> GitLabOAuthClient:
        return cast(GitLabOAuthClient, self._fakes.gitlab)


class RouteRecorder:
    """Запоминает шаблон пути сработавшей ручки — для проверки полноты покрытия.

    route.path у вложенных роутеров не содержит их префикса, поэтому сопоставляем
    реальный путь запроса с шаблонами из OpenAPI.
    """

    def __init__(self, app: ASGIApp, templates: dict[tuple[str, str], re.Pattern[str]]) -> None:
        self._app = app
        self._templates = templates

    async def __call__(self, scope: AsgiScope, receive: Receive, send: Send) -> None:
        try:
            await self._app(scope, receive, send)
        finally:
            if scope["type"] == "http" and isinstance(scope.get("route"), APIRoute):
                path = str(scope["path"]).removeprefix(API_PREFIX)
                HIT_ROUTES.update(
                    key
                    for key, pattern in self._templates.items()
                    if key[0] == scope["method"] and pattern.fullmatch(path)
                )


def _template_pattern(path: str) -> re.Pattern[str]:
    return re.compile(re.sub(r"\\\{[^}]+\\\}", "[^/]+", re.escape(path)))


@pytest.fixture
async def app(
    db: AsyncEngine,
    integration_settings: Settings,
    fakes: Fakes,
    redis: Redis,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[FastAPI]:
    def build_container(settings: Settings) -> AsyncContainer:
        return make_async_container(
            AppProvider(),
            RequestProvider(),
            FakeInfraProvider(fakes, redis),
            context={Settings: settings},
        )

    monkeypatch.setattr(tramplin.main, "build_container", build_container)
    application = create_app(integration_settings)
    # app.routes не годится: с 0.141 FastAPI держит подключённые роутеры лениво.
    routes = {
        (method.upper(), path.removeprefix(API_PREFIX))
        for path, operations in application.openapi()["paths"].items()
        for method in operations
    }
    _ALL_ROUTES.update(routes)
    application.add_middleware(
        RouteRecorder, templates={key: _template_pattern(key[1]) for key in routes}
    )
    yield application
    # ASGITransport не запускает lifespan — контейнер закрываем сами.
    await cast(AsyncContainer, application.state.dishka_container).close()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test/api/v1",
    ) as http:
        yield http


@dataclass(frozen=True, slots=True)
class Actor:
    id: uuid.UUID
    login: str
    role: UserRole
    headers: dict[str, str]


type MakeUser = Callable[..., Awaitable[Actor]]


@pytest.fixture
def make_user(db: AsyncEngine, integration_settings: Settings) -> MakeUser:
    codec = AccessTokenCodec(integration_settings)
    sessions = async_sessionmaker(db, expire_on_commit=False)

    async def factory(
        role: UserRole = UserRole.STUDENT,
        *,
        login: str | None = None,
        email: str | None = None,
        is_active: bool = True,
        identities: Sequence[IdentityProvider] = (IdentityProvider.GITHUB,),
    ) -> Actor:
        login = login or f"{role.value}-{uuid.uuid4().hex[:8]}"
        user = User(login=login, name=login.title(), email=email, role=role, is_active=is_active)
        user.identities = [
            UserIdentity(provider=provider, provider_id=f"{provider.value}-{login}", email=email)
            for provider in identities
        ]
        async with sessions.begin() as session:
            session.add(user)
        token, _ = codec.encode(user.id)
        return Actor(user.id, login, role, {"Authorization": f"Bearer {token}"})

    return factory


@pytest.fixture
async def student(make_user: MakeUser) -> Actor:
    return await make_user(UserRole.STUDENT)


@pytest.fixture
async def teacher(make_user: MakeUser) -> Actor:
    return await make_user(UserRole.TEACHER)


@pytest.fixture
async def admin(make_user: MakeUser) -> Actor:
    return await make_user(UserRole.ADMIN)


def _covers_whole_suite(config: pytest.Config) -> bool:
    """Полноту проверяем, только когда запущен весь набор интеграционных тестов."""
    if config.option.keyword or config.option.markexpr or getattr(config.option, "lf", False):
        return False
    for arg in config.args:
        path = Path(arg.split("::", 1)[0]).resolve()
        if "::" in arg or not (path == INTEGRATION_DIR or INTEGRATION_DIR.is_relative_to(path)):
            return False
    return True


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    if not _ALL_ROUTES or session.testsfailed or not _covers_whole_suite(session.config):
        return
    missing = sorted(_ALL_ROUTES - HIT_ROUTES, key=lambda item: (item[1], item[0]))
    if not missing:
        return
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if reporter is not None:
        reporter.write_sep("=", "ручки без интеграционных тестов", red=True)
        for method, path in missing:
            reporter.write_line(f"{method:6} {path}")
    session.exitstatus = pytest.ExitCode.TESTS_FAILED
