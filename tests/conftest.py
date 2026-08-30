from dataclasses import dataclass

import pytest
from pydantic import SecretStr

from tests.fakes import (
    FakeGitHubClient,
    FakeGroupRepository,
    FakeIdentityRepository,
    FakeRefreshTokenRepository,
    FakeSession,
    FakeStateStore,
    FakeUserRepository,
)
from tramplin.core.config import Settings
from tramplin.core.security import AccessTokenCodec
from tramplin.services.contracts import GitHubProfile
from tramplin.services.github_auth import GitHubAuthService
from tramplin.services.session import SessionService
from tramplin.services.users import UserService

TEST_SECRET = SecretStr("test-secret-value-at-least-32-bytes")


@dataclass(slots=True)
class AuthEnv:
    """Три сервиса на общих фейковых репозиториях плюс доступ к их содержимому."""

    github: GitHubAuthService
    sessions: SessionService
    users_service: UserService
    users: FakeUserRepository
    identities: FakeIdentityRepository
    refresh_tokens: FakeRefreshTokenRepository


@pytest.fixture
def settings() -> Settings:
    """_env_file=None: тесты не должны зависеть от локального .env разработчика."""
    return Settings(
        _env_file=None,
        jwt_secret=TEST_SECRET,
        github_client_id="cid",
        github_client_secret=SecretStr("csecret"),
    )


@pytest.fixture
def codec(settings: Settings) -> AccessTokenCodec:
    return AccessTokenCodec(settings)


@pytest.fixture
def github_profile() -> GitHubProfile:
    return GitHubProfile(
        provider_id="42",
        login="Student-One",
        name="Student One",
        email="student@example.com",
        avatar_url="https://avatars.test/42.png",
    )


@pytest.fixture
def env(settings: Settings, codec: AccessTokenCodec, github_profile: GitHubProfile) -> AuthEnv:
    session = FakeSession()
    users = FakeUserRepository()
    identities = FakeIdentityRepository(users.users)
    refresh_tokens = FakeRefreshTokenRepository()
    groups = FakeGroupRepository()
    sessions = SessionService(
        session=session,
        users=users,
        refresh_tokens=refresh_tokens,
        codec=codec,
        settings=settings,
    )
    return AuthEnv(
        github=GitHubAuthService(
            session=session,
            users=users,
            identities=identities,
            github=FakeGitHubClient(github_profile),
            state_store=FakeStateStore(),
            sessions=sessions,
        ),
        sessions=sessions,
        users_service=UserService(
            session=session,
            users=users,
            identities=identities,
            groups=groups,
        ),
        users=users,
        identities=identities,
        refresh_tokens=refresh_tokens,
    )
