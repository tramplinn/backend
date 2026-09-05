from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from urllib.parse import urlencode

import uuid_utils.compat as uuid

from tramplin.core.config import Settings
from tramplin.core.errors import AppError, ForbiddenError, UserInactiveError
from tramplin.models.enums import UserRole
from tramplin.models.users import User
from tramplin.services.contracts import Transaction
from tramplin.services.users import UserRepositoryPort, ensure_active, ensure_role


class McpOAuthError(AppError):
    status_code = 400
    message = "Некорректный OAuth-запрос"

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__()
        self.args = (code,)


@dataclass(frozen=True, slots=True)
class AuthorizationRequest:
    client_id: str
    redirect_uri: str
    state: str
    code_challenge: str
    scope: str


@dataclass(frozen=True, slots=True)
class AuthorizationCode(AuthorizationRequest):
    user_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class McpTokenPair:
    access_token: str
    access_expires_at: datetime
    refresh_token: str


class McpOAuthStorePort(Protocol):
    async def issue_request(self, request: AuthorizationRequest) -> str: ...

    async def get_request(self, request_id: str) -> AuthorizationRequest | None: ...

    async def approve(
        self, request_id: str, user_id: uuid.UUID
    ) -> tuple[AuthorizationCode, str]: ...

    async def deny(self, request_id: str) -> AuthorizationRequest | None: ...

    async def consume_code(self, code: str) -> AuthorizationCode | None: ...

    async def issue_tokens(self, user_id: uuid.UUID) -> McpTokenPair: ...

    async def consume_refresh(self, token: str) -> uuid.UUID | None: ...

    async def get_access_user(self, token: str) -> uuid.UUID | None: ...

    async def revoke(self, token: str) -> None: ...


class McpOAuthService:
    def __init__(
        self,
        transaction: Transaction,
        store: McpOAuthStorePort,
        users: UserRepositoryPort,
        settings: Settings,
    ) -> None:
        self._transaction = transaction
        self._store = store
        self._users = users
        self._settings = settings

    def authenticate_client(self, client_id: str, client_secret: str) -> None:
        import secrets

        expected = self._settings.mcp_oauth_client_secret.get_secret_value()
        if (
            not expected
            or client_id != self._settings.mcp_oauth_client_id
            or not secrets.compare_digest(client_secret, expected)
        ):
            raise McpOAuthError("invalid_client")

    async def start_authorization(
        self,
        *,
        response_type: str,
        client_id: str,
        redirect_uri: str,
        state: str,
        code_challenge: str,
        code_challenge_method: str,
        scope: str,
    ) -> str:
        if (
            response_type != "code"
            or client_id != self._settings.mcp_oauth_client_id
            or redirect_uri != self._settings.mcp_oauth_redirect_uri
            or code_challenge_method != "S256"
            or len(code_challenge) != 43
            or not state
            or scope != "authoring"
        ):
            raise McpOAuthError("invalid_request")
        request_id = await self._store.issue_request(
            AuthorizationRequest(client_id, redirect_uri, state, code_challenge, scope)
        )
        await self._transaction.commit()
        query = urlencode({"request": request_id})
        return f"{self._settings.frontend_base_url}/mcp/authorize?{query}"

    async def get_request(self, request_id: str, user: User) -> AuthorizationRequest:
        ensure_active(user)
        ensure_role(user, UserRole.TEACHER)
        request = await self._store.get_request(request_id)
        if request is None:
            raise McpOAuthError("invalid_request")
        return request

    async def approve(self, request_id: str, user: User) -> str:
        await self.get_request(request_id, user)
        try:
            authorization, code = await self._store.approve(request_id, user.id)
        except ValueError as error:
            raise McpOAuthError("invalid_request") from error
        await self._transaction.commit()
        query = urlencode({"code": code, "state": authorization.state})
        return f"{authorization.redirect_uri}?{query}"

    async def deny(self, request_id: str, user: User) -> str:
        await self.get_request(request_id, user)
        authorization = await self._store.deny(request_id)
        if authorization is None:
            raise McpOAuthError("invalid_request")
        await self._transaction.commit()
        query = urlencode({"error": "access_denied", "state": authorization.state})
        return f"{authorization.redirect_uri}?{query}"

    async def exchange_code(self, code: str, redirect_uri: str, code_verifier: str) -> McpTokenPair:
        authorization = await self._store.consume_code(code)
        if (
            authorization is None
            or authorization.client_id != self._settings.mcp_oauth_client_id
            or authorization.redirect_uri != redirect_uri
            or not _verify_pkce(code_verifier, authorization.code_challenge)
        ):
            if authorization is not None:
                await self._transaction.commit()
            raise McpOAuthError("invalid_grant")
        try:
            await self._authorized_user(authorization.user_id)
        except McpOAuthError:
            await self._transaction.commit()
            raise
        tokens = await self._store.issue_tokens(authorization.user_id)
        await self._transaction.commit()
        return tokens

    async def refresh(self, refresh_token: str) -> McpTokenPair:
        user_id = await self._store.consume_refresh(refresh_token)
        if user_id is None:
            raise McpOAuthError("invalid_grant")
        try:
            await self._authorized_user(user_id)
        except McpOAuthError:
            await self._transaction.commit()
            raise
        tokens = await self._store.issue_tokens(user_id)
        await self._transaction.commit()
        return tokens

    async def introspect(self, access_token: str) -> User:
        user_id = await self._store.get_access_user(access_token)
        if user_id is None:
            raise McpOAuthError("invalid_token")
        return await self._authorized_user(user_id, error_code="invalid_token")

    async def revoke(self, token: str) -> None:
        await self._store.revoke(token)
        await self._transaction.commit()

    async def _authorized_user(self, user_id: uuid.UUID, error_code: str = "invalid_grant") -> User:
        user = await self._users.get(user_id)
        if user is None:
            raise McpOAuthError(error_code)
        try:
            ensure_active(user)
            ensure_role(user, UserRole.TEACHER)
        except (ForbiddenError, UserInactiveError) as error:
            raise McpOAuthError(error_code) from error
        return user

    @staticmethod
    def expires_in(expires_at: datetime, now: datetime) -> int:
        return max(0, int((expires_at - now).total_seconds()))


def _verify_pkce(verifier: str, expected: str) -> bool:
    digest = hashlib.sha256(verifier.encode()).digest()
    actual = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return 43 <= len(verifier) <= 128 and actual == expected
