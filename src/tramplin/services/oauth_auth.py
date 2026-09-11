from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

import uuid_utils.compat as uuid

from tramplin.core.errors import NotFoundError, OAuthStateError
from tramplin.models.enums import IdentityProvider
from tramplin.models.users import User
from tramplin.services.contracts import OAuthProfile, OAuthState, Transaction
from tramplin.services.entity_updates import require
from tramplin.services.identity_linking import IdentityLinker
from tramplin.services.session import SessionService, TokenPair
from tramplin.services.users import UserIdentityRepositoryPort, UserRepositoryPort


class OAuthClientPort(Protocol):
    def authorize_url(self, state: str) -> str: ...

    async def exchange_code(self, code: str) -> str: ...

    async def fetch_profile(self, access_token: str) -> OAuthProfile: ...


class OAuthStateStorePort(Protocol):
    async def issue(self, state: OAuthState) -> str: ...

    async def consume(self, token: str) -> OAuthState | None: ...


@dataclass(frozen=True, slots=True)
class AuthResult:
    user: User
    tokens: TokenPair
    next_path: str


class OAuthAuthService:
    """Одна и та же логика входа для любого провайдера: различия живут в клиенте."""

    def __init__(
        self,
        session: Transaction,
        users: UserRepositoryPort,
        identities: UserIdentityRepositoryPort,
        provider: IdentityProvider,
        client: OAuthClientPort,
        state_store: OAuthStateStorePort,
        sessions: SessionService,
    ) -> None:
        self._session = session
        self._provider = provider
        self._client = client
        self._state_store = state_store
        self._sessions = sessions
        self._linker = IdentityLinker(users, identities)

    @property
    def provider(self) -> IdentityProvider:
        return self._provider

    async def start_login(self, next_path: str = "/") -> str:
        state = await self._state_store.issue(
            OAuthState(provider=self._provider, purpose="login", next_path=next_path),
        )
        return self._client.authorize_url(state)

    async def start_link(self, user_id: uuid.UUID, next_path: str = "/") -> str:
        """Привязка возможна только как явное действие залогиненного пользователя."""
        state = await self._state_store.issue(
            OAuthState(
                provider=self._provider,
                purpose="link",
                user_id=str(user_id),
                next_path=next_path,
            ),
        )
        return self._client.authorize_url(state)

    async def complete_callback(self, code: str, state_token: str) -> AuthResult:
        state = await self._state_store.consume(state_token)
        if state is None or state.provider is not self._provider:
            raise OAuthStateError

        profile = await self._client.fetch_profile(await self._client.exchange_code(code))
        if state.purpose == "link":
            if state.user_id is None:
                raise OAuthStateError
            user = await self._linker.link_identity(
                self._provider, uuid.UUID(state.user_id), profile
            )
        else:
            user = await self._linker.login_or_register(self._provider, profile)

        tokens = self._sessions.issue(user)
        await self._session.commit()
        return AuthResult(user=user, tokens=tokens, next_path=state.next_path)


class OAuthRegistry:
    """Настроенные провайдеры. Без ключей провайдера у приложения просто нет."""

    def __init__(self, services: Sequence[OAuthAuthService]) -> None:
        self._services = {service.provider: service for service in services}

    def get(self, provider: IdentityProvider) -> OAuthAuthService:
        return require(
            self._services.get(provider),
            NotFoundError(f"Вход через {provider.value} не настроен"),
        )

    @property
    def available(self) -> list[IdentityProvider]:
        return list(self._services)
