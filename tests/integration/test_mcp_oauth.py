"""OAuth 2.0 authorization server для MCP: authorize → approve → token → introspect/revoke."""

import base64
import hashlib
from typing import Any

import httpx
import pytest

from tests.integration.conftest import Actor
from tests.integration.helpers import assert_error, query_param

CLIENT_ID = "tramplin-fastmcp"
REDIRECT_URI = "http://localhost:8001/auth/callback"
VERIFIER = "v" * 64
CHALLENGE = (
    base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).rstrip(b"=").decode()
)
BASIC = {
    "Authorization": "Basic " + base64.b64encode(f"{CLIENT_ID}:mcp-client-secret".encode()).decode()
}


def _authorize_params(**overrides: str) -> dict[str, str]:
    return {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "state": "xyz",
        "code_challenge": CHALLENGE,
        "code_challenge_method": "S256",
        "scope": "authoring",
    } | overrides


async def _request_id(client: httpx.AsyncClient) -> str:
    response = await client.get("/oauth/authorize", params=_authorize_params())
    assert response.status_code == 303, response.text
    assert response.headers["location"].startswith("http://localhost:5173/mcp/authorize?")
    return query_param(response.headers["location"], "request")


async def _approved_code(client: httpx.AsyncClient, teacher: Actor) -> str:
    request_id = await _request_id(client)
    details = await client.get(f"/oauth/requests/{request_id}", headers=teacher.headers)
    assert details.json() == {"client_name": "MCP-клиент", "scope": "authoring"}

    approved = await client.post(f"/oauth/requests/{request_id}/approve", headers=teacher.headers)
    assert approved.status_code == 200, approved.text
    redirect = approved.json()["redirect_url"]
    assert redirect.startswith(REDIRECT_URI)
    assert query_param(redirect, "state") == "xyz"
    return query_param(redirect, "code")


async def _token(client: httpx.AsyncClient, form: dict[str, str]) -> httpx.Response:
    return await client.post("/oauth/token", data=form, headers=BASIC)


async def _exchange(client: httpx.AsyncClient, teacher: Actor) -> dict[str, Any]:
    code = await _approved_code(client, teacher)
    response = await _token(
        client,
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": VERIFIER,
        },
    )
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    tokens: dict[str, Any] = response.json()
    return tokens


async def test_full_flow_issues_working_tokens(client: httpx.AsyncClient, teacher: Actor) -> None:
    tokens = await _exchange(client, teacher)
    assert tokens["token_type"] == "Bearer"  # noqa: S105 - тип токена, не секрет
    assert tokens["scope"] == "authoring"

    bearer = {"Authorization": f"Bearer {tokens['access_token']}"}
    introspection = await client.get("/oauth/introspect", headers=bearer)
    assert introspection.json() == {
        "active": True,
        "sub": str(teacher.id),
        "login": teacher.login,
        "role": "teacher",
        "scope": "authoring",
    }
    # Opaque-токен MCP годится для authoring-ручек.
    assert (await client.get("/authoring/tracks", headers=bearer)).status_code == 200


async def test_refresh_grant_rotates_tokens(client: httpx.AsyncClient, teacher: Actor) -> None:
    tokens = await _exchange(client, teacher)

    refreshed = await _token(
        client, {"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"]}
    )
    assert refreshed.status_code == 200
    assert refreshed.json()["access_token"] != tokens["access_token"]

    replay = await _token(
        client, {"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"]}
    )
    assert replay.status_code == 400
    assert replay.json() == {"error": "invalid_grant"}


async def test_code_is_single_use_and_checks_pkce(
    client: httpx.AsyncClient, teacher: Actor
) -> None:
    code = await _approved_code(client, teacher)
    form = {"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT_URI}

    bad_verifier = await _token(client, form | {"code_verifier": "w" * 64})
    assert bad_verifier.json() == {"error": "invalid_grant"}

    # Неудачная попытка всё равно сжигает код.
    retry = await _token(client, form | {"code_verifier": VERIFIER})
    assert retry.json() == {"error": "invalid_grant"}


async def test_revoke(client: httpx.AsyncClient, teacher: Actor) -> None:
    tokens = await _exchange(client, teacher)

    response = await client.post(
        "/oauth/revoke", data={"token": tokens["access_token"]}, headers=BASIC
    )

    assert response.status_code == 204
    introspection = await client.get(
        "/oauth/introspect", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    assert_error(introspection, 401, "invalid_token")


async def test_deny(client: httpx.AsyncClient, teacher: Actor) -> None:
    request_id = await _request_id(client)

    response = await client.post(f"/oauth/requests/{request_id}/deny", headers=teacher.headers)

    assert response.status_code == 200
    assert query_param(response.json()["redirect_url"], "error") == "access_denied"
    again = await client.post(f"/oauth/requests/{request_id}/approve", headers=teacher.headers)
    assert again.status_code == 400


@pytest.mark.parametrize(
    "override",
    [
        {"client_id": "evil"},
        {"redirect_uri": "http://evil.test/cb"},
        {"code_challenge_method": "plain"},
        {"scope": "admin"},
    ],
)
async def test_authorize_rejects_invalid_request(
    client: httpx.AsyncClient, override: dict[str, str]
) -> None:
    response = await client.get("/oauth/authorize", params=_authorize_params(**override))

    assert response.status_code == 400
    assert response.json() == {"error": "invalid_request"}


async def test_student_cannot_see_request(client: httpx.AsyncClient, student: Actor) -> None:
    request_id = await _request_id(client)

    response = await client.get(f"/oauth/requests/{request_id}", headers=student.headers)

    assert response.status_code == 403


async def test_token_requires_client_credentials(client: httpx.AsyncClient) -> None:
    response = await client.post("/oauth/token", data={"grant_type": "refresh_token"})

    assert response.status_code == 401
    assert response.json() == {"error": "invalid_client"}


async def test_revoke_requires_client_credentials(client: httpx.AsyncClient) -> None:
    wrong = {"Authorization": "Basic " + base64.b64encode(b"tramplin-fastmcp:nope").decode()}

    response = await client.post("/oauth/revoke", data={"token": "x"}, headers=wrong)

    assert response.json() == {"error": "invalid_client"}


async def test_unsupported_grant_type(client: httpx.AsyncClient) -> None:
    response = await _token(client, {"grant_type": "password"})

    assert response.json() == {"error": "unsupported_grant_type"}


async def test_introspect_without_token(client: httpx.AsyncClient) -> None:
    assert (await client.get("/oauth/introspect")).status_code == 401
