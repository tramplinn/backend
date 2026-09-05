import base64
import hashlib
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, cast
from unittest.mock import Mock
from urllib.parse import parse_qs, urlparse

import pytest
import uuid_utils.compat as uuid

from tests.conftest import AuthEnv
from tramplin.api.v1.auth import _basic_client, _urlencoded
from tramplin.core.config import Settings
from tramplin.core.errors import ForbiddenError, UserInactiveError
from tramplin.core.security import sha256_hex
from tramplin.core.time import utc_now
from tramplin.infrastructure.repositories.mcp_oauth import McpOAuthRepository
from tramplin.models.enums import UserRole
from tramplin.models.mcp_oauth import McpOAuthAuthorization, McpOAuthToken
from tramplin.models.users import User
from tramplin.services.mcp_oauth import (
    AuthorizationCode,
    AuthorizationRequest,
    McpOAuthError,
    McpOAuthService,
    McpTokenPair,
)

VERIFIER = "v" * 43


class FakeMcpOAuthStore:
    def __init__(self) -> None:
        self.requests: dict[str, AuthorizationRequest] = {}
        self.codes: dict[str, AuthorizationCode] = {}
        self.access: dict[str, uuid.UUID] = {}
        self.refresh: dict[str, uuid.UUID] = {}
        self.token_sequence = 0

    async def issue_request(self, request: AuthorizationRequest) -> str:
        self.requests["request-1"] = request
        return "request-1"

    async def get_request(self, request_id: str) -> AuthorizationRequest | None:
        return self.requests.get(request_id)

    async def approve(self, request_id: str, user_id: uuid.UUID) -> tuple[AuthorizationCode, str]:
        request = self.requests.pop(request_id, None)
        if request is None:
            raise ValueError
        authorization = AuthorizationCode(
            client_id=request.client_id,
            redirect_uri=request.redirect_uri,
            state=request.state,
            code_challenge=request.code_challenge,
            scope=request.scope,
            user_id=user_id,
        )
        self.codes["code-1"] = authorization
        return authorization, "code-1"

    async def deny(self, request_id: str) -> AuthorizationRequest | None:
        return self.requests.pop(request_id, None)

    async def consume_code(self, code: str) -> AuthorizationCode | None:
        return self.codes.pop(code, None)

    async def issue_tokens(self, user_id: uuid.UUID) -> McpTokenPair:
        self.token_sequence += 1
        access_token = f"access-{self.token_sequence}"
        refresh_token = f"refresh-{self.token_sequence}"
        self.access[access_token] = user_id
        self.refresh[refresh_token] = user_id
        return McpTokenPair(
            access_token,
            utc_now() + timedelta(minutes=15),
            refresh_token,
        )

    async def consume_refresh(self, token: str) -> uuid.UUID | None:
        return self.refresh.pop(token, None)

    async def get_access_user(self, token: str) -> uuid.UUID | None:
        return self.access.get(token)

    async def revoke(self, token: str) -> None:
        self.access.pop(token, None)
        self.refresh.pop(token, None)


@dataclass(slots=True)
class McpEnv:
    service: McpOAuthService
    store: FakeMcpOAuthStore
    auth: AuthEnv
    settings: Settings
    teacher: User


@pytest.fixture
def mcp_env(env: AuthEnv, settings: Settings) -> McpEnv:
    store = FakeMcpOAuthStore()
    teacher = env.users.add(User(login="teacher", role=UserRole.TEACHER, is_active=True))
    return McpEnv(
        service=McpOAuthService(env.sessions._session, store, env.users, settings),
        store=store,
        auth=env,
        settings=settings,
        teacher=teacher,
    )


def pkce(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


async def start(env: McpEnv, verifier: str = VERIFIER) -> str:
    return await env.service.start_authorization(
        response_type="code",
        client_id=env.settings.mcp_oauth_client_id,
        redirect_uri=env.settings.mcp_oauth_redirect_uri,
        state="client-state",
        code_challenge=pkce(verifier),
        code_challenge_method="S256",
        scope="authoring",
    )


async def test_authorization_code_flow_issues_rotatable_session(mcp_env: McpEnv) -> None:
    consent_url = await start(mcp_env)
    assert consent_url.endswith("/mcp/authorize?request=request-1")
    assert (await mcp_env.service.get_request("request-1", mcp_env.teacher)).scope == "authoring"

    callback = await mcp_env.service.approve("request-1", mcp_env.teacher)
    assert parse_qs(urlparse(callback).query) == {
        "code": ["code-1"],
        "state": ["client-state"],
    }
    tokens = await mcp_env.service.exchange_code(
        "code-1", mcp_env.settings.mcp_oauth_redirect_uri, VERIFIER
    )
    assert (await mcp_env.service.introspect(tokens.access_token)).id == mcp_env.teacher.id

    web_tokens = mcp_env.auth.sessions.issue(mcp_env.teacher)
    with pytest.raises(McpOAuthError, match="invalid_token"):
        await mcp_env.service.introspect(web_tokens.access_token)

    rotated = await mcp_env.service.refresh(tokens.refresh_token)
    assert rotated.refresh_token != tokens.refresh_token
    await mcp_env.service.revoke(rotated.refresh_token)
    with pytest.raises(McpOAuthError, match="invalid_grant"):
        await mcp_env.service.refresh(rotated.refresh_token)


async def test_denial_returns_oauth_error_to_client_and_consumes_request(mcp_env: McpEnv) -> None:
    await start(mcp_env)

    callback = await mcp_env.service.deny("request-1", mcp_env.teacher)

    assert parse_qs(urlparse(callback).query) == {
        "error": ["access_denied"],
        "state": ["client-state"],
    }
    with pytest.raises(McpOAuthError, match="invalid_request"):
        await mcp_env.service.deny("request-1", mcp_env.teacher)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("response_type", "token"),
        ("client_id", "unknown"),
        ("redirect_uri", "https://attacker.example/callback"),
        ("code_challenge_method", "plain"),
        ("scope", "admin"),
    ],
)
async def test_authorize_rejects_invalid_protocol_parameters(
    mcp_env: McpEnv, field: str, value: str
) -> None:
    values = {
        "response_type": "code",
        "client_id": mcp_env.settings.mcp_oauth_client_id,
        "redirect_uri": mcp_env.settings.mcp_oauth_redirect_uri,
        "state": "state",
        "code_challenge": pkce(VERIFIER),
        "code_challenge_method": "S256",
        "scope": "authoring",
    }
    values[field] = value

    with pytest.raises(McpOAuthError, match="invalid_request"):
        await mcp_env.service.start_authorization(**values)


async def test_only_active_teacher_or_admin_can_authorize(mcp_env: McpEnv) -> None:
    await start(mcp_env)
    student = User(login="student", role=UserRole.STUDENT, is_active=True)
    inactive = User(login="inactive", role=UserRole.TEACHER, is_active=False)

    with pytest.raises(ForbiddenError):
        await mcp_env.service.get_request("request-1", student)
    with pytest.raises(UserInactiveError):
        await mcp_env.service.get_request("request-1", inactive)

    admin = User(login="admin", role=UserRole.ADMIN, is_active=True)
    assert await mcp_env.service.get_request("request-1", admin) is not None


async def test_code_is_one_time_and_bound_to_redirect_and_pkce(mcp_env: McpEnv) -> None:
    await start(mcp_env)
    await mcp_env.service.approve("request-1", mcp_env.teacher)

    with pytest.raises(McpOAuthError, match="invalid_grant"):
        await mcp_env.service.exchange_code("code-1", "https://wrong.example", VERIFIER)
    with pytest.raises(McpOAuthError, match="invalid_grant"):
        await mcp_env.service.exchange_code(
            "code-1", mcp_env.settings.mcp_oauth_redirect_uri, VERIFIER
        )


async def test_code_rejects_wrong_pkce_and_missing_user(mcp_env: McpEnv) -> None:
    await start(mcp_env)
    await mcp_env.service.approve("request-1", mcp_env.teacher)
    with pytest.raises(McpOAuthError, match="invalid_grant"):
        await mcp_env.service.exchange_code(
            "code-1", mcp_env.settings.mcp_oauth_redirect_uri, "wrong"
        )

    await start(mcp_env)
    await mcp_env.service.approve("request-1", mcp_env.teacher)
    mcp_env.auth.users.users.clear()
    with pytest.raises(McpOAuthError, match="invalid_grant"):
        await mcp_env.service.exchange_code(
            "code-1", mcp_env.settings.mcp_oauth_redirect_uri, VERIFIER
        )


async def test_invalid_refresh_is_an_oauth_grant_error(mcp_env: McpEnv) -> None:
    with pytest.raises(McpOAuthError, match="invalid_grant"):
        await mcp_env.service.refresh("unknown")


def test_client_auth_and_form_helpers(mcp_env: McpEnv) -> None:
    credentials = base64.b64encode(b"tramplin-fastmcp:mcp-client-secret").decode()
    assert _basic_client(f"Basic {credentials}") == (
        "tramplin-fastmcp",
        "mcp-client-secret",
    )
    assert _urlencoded(b"grant_type=authorization_code&code=last&code=winner") == {
        "grant_type": "authorization_code",
        "code": "winner",
    }
    mcp_env.service.authenticate_client("tramplin-fastmcp", "mcp-client-secret")
    for header in (None, "Bearer token", "Basic !!!"):
        with pytest.raises(McpOAuthError, match="invalid_client"):
            _basic_client(header)
    with pytest.raises(McpOAuthError, match="invalid_client"):
        mcp_env.service.authenticate_client("tramplin-fastmcp", "wrong")


def test_expires_in_never_returns_negative(mcp_env: McpEnv) -> None:
    now = utc_now()
    assert mcp_env.service.expires_in(now + timedelta(seconds=10), now) == 10
    assert mcp_env.service.expires_in(now - timedelta(seconds=1), now) == 0


class ScalarFake:
    def __init__(self, value: object | None) -> None:
        self.value = value

    def one_or_none(self) -> object | None:
        return self.value


class DbSessionFake:
    def __init__(self, *results: object | None) -> None:
        self.results = list(results)
        self.add = Mock()
        self.deleted: list[object] = []

    async def scalars(self, _: object) -> ScalarFake:
        return ScalarFake(self.results.pop(0) if self.results else None)

    async def delete(self, value: object) -> None:
        self.deleted.append(value)


def authorization_record(request: AuthorizationRequest) -> McpOAuthAuthorization:
    return McpOAuthAuthorization(
        request_hash=sha256_hex("request"),
        client_id=request.client_id,
        redirect_uri=request.redirect_uri,
        state=request.state,
        code_challenge=request.code_challenge,
        scope=request.scope,
        request_expired_at=utc_now() + timedelta(minutes=10),
    )


async def test_database_authorization_repository(settings: Settings) -> None:
    request = AuthorizationRequest(
        client_id="client",
        redirect_uri="https://client.example/callback",
        state="state",
        code_challenge="challenge",
        scope="authoring",
    )

    issue_session = DbSessionFake()
    request_id = await McpOAuthRepository(cast(Any, issue_session), settings).issue_request(request)
    issued = issue_session.add.call_args.args[0]
    assert issued.request_hash == sha256_hex(request_id)

    record = authorization_record(request)
    store = McpOAuthRepository(cast(Any, DbSessionFake(record, record)), settings)
    assert await store.get_request("request") == request
    user_id = User(login="u").id
    authorization, code = await store.approve("request", user_id)
    assert authorization.state == "state"
    assert record.request_hash is None
    assert record.code_hash == sha256_hex(code)

    code_store = McpOAuthRepository(cast(Any, DbSessionFake(record, None)), settings)
    assert await code_store.consume_code(code) == authorization
    assert record.consumed_at is not None
    assert await code_store.consume_code(code) is None

    denied = authorization_record(request)
    deny_session = DbSessionFake(denied, None, None)
    deny_store = McpOAuthRepository(cast(Any, deny_session), settings)
    assert await deny_store.deny("request") == request
    assert deny_session.deleted == [denied]
    assert await deny_store.deny("request") is None
    with pytest.raises(ValueError, match="missing"):
        await deny_store.approve("unknown", user_id)


async def test_database_token_repository(settings: Settings) -> None:
    user_id = User(login="teacher").id
    issue_session = DbSessionFake()
    issue_store = McpOAuthRepository(cast(Any, issue_session), settings)
    tokens = await issue_store.issue_tokens(user_id)
    issued = issue_session.add.call_args.args[0]
    assert issued.access_hash == sha256_hex(tokens.access_token)
    assert issued.refresh_hash == sha256_hex(tokens.refresh_token)

    token_record = cast(McpOAuthToken, issued)
    store = McpOAuthRepository(
        cast(Any, DbSessionFake(user_id, token_record, None, token_record)), settings
    )
    assert await store.get_access_user(tokens.access_token) == user_id
    assert await store.consume_refresh(tokens.refresh_token) == user_id
    assert token_record.refresh_hash is None
    assert await store.consume_refresh(tokens.refresh_token) is None
    await store.revoke(tokens.access_token)
    assert token_record.access_hash is None
    assert token_record.revoked_at is not None
