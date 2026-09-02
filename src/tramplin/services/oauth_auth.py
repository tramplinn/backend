import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Protocol

import uuid_utils.compat as uuid

from tramplin.core.errors import (
    ConflictError,
    IdentityAlreadyLinkedError,
    NotFoundError,
    OAuthStateError,
)
from tramplin.models.enums import IdentityProvider, UserRole
from tramplin.models.users import User, UserIdentity
from tramplin.services.contracts import OAuthProfile, OAuthState, Transaction
from tramplin.services.session import SessionService, TokenPair
from tramplin.services.users import (
    UserIdentityRepositoryPort,
    UserRepositoryPort,
    ensure_active,
)


class OAuthClientPort(Protocol):
    def authorize_url(self, state: str) -> str: ...

    async def exchange_code(self, code: str) -> str: ...

    async def fetch_profile(self, access_token: str) -> OAuthProfile: ...


class OAuthStateStorePort(Protocol):
    async def issue(self, state: OAuthState) -> str: ...

    async def consume(self, token: str) -> OAuthState | None: ...


logger = logging.getLogger(__name__)

LOGIN_FORBIDDEN: Final = re.compile(r"[^a-z0-9_-]+")
FALLBACK_LOGIN: Final = "student"
MAX_LOGIN_LENGTH: Final = 48
MAX_LOGIN_SUFFIX: Final = 50


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
        self._users = users
        self._identities = identities
        self._provider = provider
        self._client = client
        self._state_store = state_store
        self._sessions = sessions

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
        user = (
            await self._link_identity(state, profile)
            if state.purpose == "link"
            else await self._login_or_register(profile)
        )

        tokens = self._sessions.issue(user)
        await self._session.commit()
        return AuthResult(user=user, tokens=tokens, next_path=state.next_path)

    async def _login_or_register(self, profile: OAuthProfile) -> User:
        identity = await self._identities.get_by_provider(self._provider, profile.provider_id)
        if identity is not None:
            ensure_active(identity.user)
            self._fill_profile(identity.user, profile)
            return identity.user

        user = User(
            login=await self._unique_login(profile.login),
            name=profile.name,
            email=profile.email,
            avatar_url=profile.avatar_url,
            role=UserRole.STUDENT,
            is_active=True,
        )
        user.created_by = user.id
        user.updated_by = user.id
        self._users.add(user)
        self._add_identity(user, profile)
        logger.info("registered user via %s: %s", self._provider.value, user.id)
        return user

    async def _link_identity(self, state: OAuthState, profile: OAuthProfile) -> User:
        if state.user_id is None:
            raise OAuthStateError
        user = await self._users.get(uuid.UUID(state.user_id))
        if user is None:
            raise NotFoundError("Пользователь не найден")
        ensure_active(user)

        existing = await self._identities.get_by_provider(self._provider, profile.provider_id)
        if existing is not None:
            if existing.user_id != user.id:
                raise IdentityAlreadyLinkedError
            return user
        if await self._identities.get_for_user(user.id, self._provider) is not None:
            raise ConflictError(f"У пользователя уже привязан аккаунт {self._provider.value}")

        self._add_identity(user, profile)
        self._fill_profile(user, profile)
        return user

    def _add_identity(self, user: User, profile: OAuthProfile) -> None:
        self._identities.add(
            UserIdentity(
                user_id=user.id,
                provider=self._provider,
                provider_id=profile.provider_id,
                email=profile.email,
                created_by=user.id,
                updated_by=user.id,
            ),
        )

    async def _unique_login(self, raw_login: str) -> str:
        cleaned = LOGIN_FORBIDDEN.sub("-", raw_login.strip().lower()).strip("-")
        base = cleaned[:MAX_LOGIN_LENGTH] or FALLBACK_LOGIN
        if not await self._users.login_exists(base):
            return base
        for suffix in range(2, MAX_LOGIN_SUFFIX):
            candidate = f"{base}-{suffix}"
            if not await self._users.login_exists(candidate):
                return candidate
        raise ConflictError("Не удалось подобрать свободный логин")

    @staticmethod
    def _fill_profile(user: User, profile: OAuthProfile) -> None:
        """Заполняем только пустые поля: правки в админке не затираются логином."""
        user.name = user.name or profile.name
        user.email = user.email or profile.email
        user.avatar_url = profile.avatar_url or user.avatar_url
        user.updated_by = user.id


class OAuthRegistry:
    """Настроенные провайдеры. Без ключей провайдера у приложения просто нет."""

    def __init__(self, services: Sequence[OAuthAuthService]) -> None:
        self._services = {service.provider: service for service in services}

    def get(self, provider: IdentityProvider) -> OAuthAuthService:
        service = self._services.get(provider)
        if service is None:
            raise NotFoundError(f"Вход через {provider.value} не настроен")
        return service

    @property
    def available(self) -> list[IdentityProvider]:
        return list(self._services)
