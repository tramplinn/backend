import logging
import re
from typing import Final

import uuid_utils.compat as uuid

from tramplin.core.errors import ConflictError, IdentityAlreadyLinkedError, NotFoundError
from tramplin.models.enums import IdentityProvider, UserRole
from tramplin.models.users import User, UserIdentity
from tramplin.services.contracts import OAuthProfile
from tramplin.services.entity_updates import require
from tramplin.services.users import UserIdentityRepositoryPort, UserRepositoryPort, ensure_active

logger = logging.getLogger(__name__)

LOGIN_FORBIDDEN: Final = re.compile(r"[^a-z0-9_-]+")
FALLBACK_LOGIN: Final = "student"
MAX_LOGIN_LENGTH: Final = 48
MAX_LOGIN_SUFFIX: Final = 50


class IdentityLinker:
    """Регистрация/привязка провайдера к пользователю — общая для OAuth и почты:
    различие в том, откуда берётся OAuthProfile, не в том, что с ним делать."""

    def __init__(self, users: UserRepositoryPort, identities: UserIdentityRepositoryPort) -> None:
        self._users = users
        self._identities = identities

    async def login_or_register(self, provider: IdentityProvider, profile: OAuthProfile) -> User:
        identity = await self._identities.get_by_provider(provider, profile.provider_id)
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
        self._add_identity(user, provider, profile)
        logger.info("registered user via %s: %s", provider.value, user.id)
        return user

    async def link_identity(
        self,
        provider: IdentityProvider,
        user_id: uuid.UUID,
        profile: OAuthProfile,
    ) -> User:
        user = require(await self._users.get(user_id), NotFoundError("Пользователь не найден"))
        ensure_active(user)

        existing = await self._identities.get_by_provider(provider, profile.provider_id)
        if existing is not None:
            if existing.user_id != user.id:
                raise IdentityAlreadyLinkedError
            return user
        if await self._identities.get_for_user(user.id, provider) is not None:
            raise ConflictError(f"У пользователя уже привязан аккаунт {provider.value}")

        self._add_identity(user, provider, profile)
        self._fill_profile(user, profile)
        return user

    def _add_identity(self, user: User, provider: IdentityProvider, profile: OAuthProfile) -> None:
        self._identities.add(
            UserIdentity(
                user_id=user.id,
                provider=provider,
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
        user.avatar_url = user.avatar_url or profile.avatar_url
        user.updated_by = user.id
