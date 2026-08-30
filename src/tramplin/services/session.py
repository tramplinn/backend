from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

import uuid_utils.compat as uuid

from tramplin.core.config import Settings
from tramplin.core.errors import InvalidTokenError
from tramplin.core.security import AccessTokenCodec, generate_refresh_token, sha256_hex
from tramplin.core.time import utc_now
from tramplin.models.users import RefreshToken, User
from tramplin.services.contracts import Transaction
from tramplin.services.users import UserRepositoryPort, ensure_active


class RefreshTokenRepositoryPort(Protocol):
    async def consume_by_hash(self, token_hash: str) -> RefreshToken | None: ...

    def add(self, token: RefreshToken) -> RefreshToken: ...

    async def delete_for_user(self, user_id: uuid.UUID) -> int: ...


@dataclass(frozen=True, slots=True)
class TokenPair:
    access_token: str
    access_expires_at: datetime
    refresh_token: str


class SessionService:
    """Слой сессий поверх OAuth: короткий access-JWT и ротируемый refresh в базе."""

    def __init__(
        self,
        session: Transaction,
        users: UserRepositoryPort,
        refresh_tokens: RefreshTokenRepositoryPort,
        codec: AccessTokenCodec,
        settings: Settings,
    ) -> None:
        self._session = session
        self._users = users
        self._refresh_tokens = refresh_tokens
        self._codec = codec
        self._settings = settings

    def issue(self, user: User) -> TokenPair:
        """Без commit: транзакцию закрывает вызывающий сервис вместе со своими изменениями."""
        access_token, access_expires_at = self._codec.encode(user.id)
        raw_refresh, refresh_hash = generate_refresh_token(self._settings.refresh_token_bytes)
        self._refresh_tokens.add(
            RefreshToken(
                user_id=user.id,
                token_hash=refresh_hash,
                expired_at=utc_now() + self._settings.refresh_token_ttl,
                created_by=user.id,
                updated_by=user.id,
            ),
        )
        return TokenPair(
            access_token=access_token,
            access_expires_at=access_expires_at,
            refresh_token=raw_refresh,
        )

    async def refresh(self, raw_refresh_token: str) -> TokenPair:
        """Ротация: прежняя строка удаляется, повторное использование токена невозможно."""
        stored = await self._refresh_tokens.consume_by_hash(sha256_hex(raw_refresh_token))
        if stored is None:
            raise InvalidTokenError

        expired = stored.expired_at <= utc_now()
        user = await self._users.get(stored.user_id)
        if expired or user is None:
            await self._session.commit()
            raise InvalidTokenError
        ensure_active(user)

        tokens = self.issue(user)
        await self._session.commit()
        return tokens

    async def logout(self, raw_refresh_token: str | None) -> None:
        if raw_refresh_token:
            await self._refresh_tokens.consume_by_hash(sha256_hex(raw_refresh_token))
        await self._session.commit()

    async def logout_everywhere(self, user_id: uuid.UUID) -> int:
        removed = await self._refresh_tokens.delete_for_user(user_id)
        await self._session.commit()
        return removed

    async def authenticate(self, access_token: str) -> User:
        user = await self._users.get(self._codec.decode(access_token))
        if user is None:
            raise InvalidTokenError
        ensure_active(user)
        return user
