import uuid_utils.compat as uuid
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from tramplin.core.config import Settings
from tramplin.core.security import generate_token, sha256_hex
from tramplin.core.time import utc_now
from tramplin.infrastructure.repositories.base import Repository
from tramplin.models.mcp_oauth import McpOAuthAuthorization, McpOAuthToken
from tramplin.services.mcp_oauth import AuthorizationCode, AuthorizationRequest, McpTokenPair


class McpOAuthRepository(Repository):
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        super().__init__(session)
        self._request_ttl = settings.mcp_oauth_request_ttl
        self._code_ttl = settings.mcp_oauth_code_ttl
        self._access_ttl = settings.access_token_ttl
        self._refresh_ttl = settings.refresh_token_ttl

    async def issue_request(self, request: AuthorizationRequest) -> str:
        raw = generate_token(32)
        self._session.add(
            McpOAuthAuthorization(
                request_hash=sha256_hex(raw),
                client_id=request.client_id,
                redirect_uri=request.redirect_uri,
                state=request.state,
                code_challenge=request.code_challenge,
                scope=request.scope,
                request_expired_at=utc_now() + self._request_ttl,
            )
        )
        return raw

    async def get_request(self, request_id: str) -> AuthorizationRequest | None:
        record = await self._request_record(request_id, lock=False)
        return None if record is None else _request(record)

    async def approve(self, request_id: str, user_id: uuid.UUID) -> tuple[AuthorizationCode, str]:
        record = await self._request_record(request_id, lock=True)
        if record is None:
            raise ValueError("authorization request is missing")
        code = generate_token(32)
        record.request_hash = None
        record.code_hash = sha256_hex(code)
        record.code_expired_at = utc_now() + self._code_ttl
        record.user_id = user_id
        record.updated_by = user_id
        return _authorization(record, user_id), code

    async def deny(self, request_id: str) -> AuthorizationRequest | None:
        record = await self._request_record(request_id, lock=True)
        if record is None:
            return None
        request = _request(record)
        await self._session.delete(record)
        return request

    async def consume_code(self, code: str) -> AuthorizationCode | None:
        now = utc_now()
        stmt = (
            select(McpOAuthAuthorization)
            .where(
                McpOAuthAuthorization.code_hash == sha256_hex(code),
                McpOAuthAuthorization.code_expired_at > now,
                McpOAuthAuthorization.consumed_at.is_(None),
            )
            .with_for_update()
        )
        record = (await self._session.scalars(stmt)).one_or_none()
        if record is None or record.user_id is None:
            return None
        record.code_hash = None
        record.consumed_at = now
        record.updated_by = record.user_id
        return _authorization(record, record.user_id)

    async def issue_tokens(self, user_id: uuid.UUID) -> McpTokenPair:
        now = utc_now()
        access_token = generate_token(32)
        refresh_token = generate_token(48)
        access_expired_at = now + self._access_ttl
        self._session.add(
            McpOAuthToken(
                user_id=user_id,
                access_hash=sha256_hex(access_token),
                refresh_hash=sha256_hex(refresh_token),
                access_expired_at=access_expired_at,
                refresh_expired_at=now + self._refresh_ttl,
                created_by=user_id,
                updated_by=user_id,
            )
        )
        return McpTokenPair(access_token, access_expired_at, refresh_token)

    async def consume_refresh(self, token: str) -> uuid.UUID | None:
        now = utc_now()
        stmt = (
            select(McpOAuthToken)
            .where(
                McpOAuthToken.refresh_hash == sha256_hex(token),
                McpOAuthToken.refresh_expired_at > now,
                McpOAuthToken.revoked_at.is_(None),
            )
            .with_for_update()
        )
        record = (await self._session.scalars(stmt)).one_or_none()
        if record is None:
            return None
        record.refresh_hash = None
        record.updated_by = record.user_id
        return record.user_id

    async def get_access_user(self, token: str) -> uuid.UUID | None:
        stmt = select(McpOAuthToken.user_id).where(
            McpOAuthToken.access_hash == sha256_hex(token),
            McpOAuthToken.access_expired_at > utc_now(),
            McpOAuthToken.revoked_at.is_(None),
        )
        return (await self._session.scalars(stmt)).one_or_none()

    async def revoke(self, token: str) -> None:
        token_hash = sha256_hex(token)
        stmt = (
            select(McpOAuthToken)
            .where(
                or_(
                    McpOAuthToken.access_hash == token_hash,
                    McpOAuthToken.refresh_hash == token_hash,
                )
            )
            .with_for_update()
        )
        record = (await self._session.scalars(stmt)).one_or_none()
        if record is not None:
            record.access_hash = None
            record.refresh_hash = None
            record.revoked_at = utc_now()
            record.updated_by = record.user_id

    async def _request_record(self, request_id: str, *, lock: bool) -> McpOAuthAuthorization | None:
        stmt = select(McpOAuthAuthorization).where(
            McpOAuthAuthorization.request_hash == sha256_hex(request_id),
            McpOAuthAuthorization.request_expired_at > utc_now(),
        )
        if lock:
            stmt = stmt.with_for_update()
        return (await self._session.scalars(stmt)).one_or_none()


def _request(record: McpOAuthAuthorization) -> AuthorizationRequest:
    return AuthorizationRequest(
        record.client_id,
        record.redirect_uri,
        record.state,
        record.code_challenge,
        record.scope,
    )


def _authorization(record: McpOAuthAuthorization, user_id: uuid.UUID) -> AuthorizationCode:
    return AuthorizationCode(
        record.client_id,
        record.redirect_uri,
        record.state,
        record.code_challenge,
        record.scope,
        user_id,
    )
