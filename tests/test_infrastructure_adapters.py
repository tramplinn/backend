from datetime import timedelta
from typing import Any, cast
from unittest.mock import AsyncMock

import httpx
import pytest
from botocore.exceptions import BotoCoreError
from pydantic import SecretStr

from tests.conftest import TEST_SECRET
from tramplin.core.config import Environment, Settings, _parse_duration, load_settings
from tramplin.core.errors import OAuthProviderError, StorageError
from tramplin.infrastructure.github import GitHubOAuthClient, _parse_profile, replace_email
from tramplin.infrastructure.gitlab import GitLabOAuthClient
from tramplin.infrastructure.oauth_http import as_object, body
from tramplin.infrastructure.oauth_http import text as text_or_none
from tramplin.infrastructure.oauth_state import OAuthStateStore
from tramplin.infrastructure.redis_store import RedisNamespace, _decode
from tramplin.infrastructure.s3_storage import S3Storage
from tramplin.infrastructure.yandex import YandexOAuthClient
from tramplin.models.enums import AssetMime, IdentityProvider
from tramplin.services.contracts import OAuthProfile, OAuthState


def response(status: int, payload: Any = None, *, text: str | None = None) -> httpx.Response:
    request = httpx.Request("GET", "https://github.test/resource")
    if text is not None:
        return httpx.Response(status, text=text, request=request)
    return httpx.Response(status, json=payload, request=request)


async def test_github_client_success_and_email_fallback(settings: Settings) -> None:
    http = cast(Any, type("HttpFake", (), {"post": AsyncMock(), "get": AsyncMock()})())
    client = GitHubOAuthClient(settings, http)
    assert "state=state" in client.authorize_url("state")

    http.post.return_value = response(200, {"access_token": "token"})
    assert await client.exchange_code("code") == "token"

    profile_payload = {
        "id": 7,
        "login": "octocat",
        "name": "Octo",
        "email": "octo@example.test",
        "avatar_url": "https://example.test/a.png",
    }
    http.get.return_value = response(200, profile_payload)
    assert (await client.fetch_profile("token")).email == "octo@example.test"

    hidden_email = profile_payload | {"email": None}
    http.get.side_effect = [
        response(200, hidden_email),
        response(
            200,
            [
                {"email": "ignored@example.test", "primary": False, "verified": True},
                {"email": "primary@example.test", "primary": True, "verified": True},
            ],
        ),
    ]
    assert (await client.fetch_profile("token")).email == "primary@example.test"

    http.get.side_effect = [response(200, hidden_email), response(500, {})]
    assert (await client.fetch_profile("token")).email is None
    http.get.side_effect = [response(200, hidden_email), response(200, {"not": "a list"})]
    assert (await client.fetch_profile("token")).email is None


def test_oauth_response_validation() -> None:
    profile = OAuthProfile("1", "user", None, None, None)
    assert replace_email(profile, "mail@example.test").email == "mail@example.test"
    assert _parse_profile({"id": 1, "login": "user"}).provider_id == "1"
    assert text_or_none(1) is None
    assert text_or_none("") is None
    assert text_or_none("ok") == "ok"
    assert as_object({"ok": True}, "GitHub") == {"ok": True}

    with pytest.raises(OAuthProviderError):
        _parse_profile({"login": "user"})
    with pytest.raises(OAuthProviderError):
        as_object([], "GitHub")
    with pytest.raises(OAuthProviderError):
        body(response(500, {}), "GitHub")
    with pytest.raises(OAuthProviderError):
        body(response(200, text="not-json"), "GitHub")
    assert body(response(200, text="not-json"), "GitHub", strict=False) is None


def yandex_settings() -> Settings:
    return Settings(
        _env_file=None,
        jwt_secret=TEST_SECRET,
        github_client_id="cid",
        github_client_secret=SecretStr("csecret"),
        yandex_client_id="ycid",
        yandex_client_secret=SecretStr("ysecret"),
    )


async def test_yandex_client_reads_profile_and_builds_avatar_url() -> None:
    http = cast(Any, type("HttpFake", (), {"post": AsyncMock(), "get": AsyncMock()})())
    client = YandexOAuthClient(yandex_settings(), http)
    assert "state=state" in client.authorize_url("state")
    assert "response_type=code" in client.authorize_url("state")

    http.post.return_value = response(200, {"access_token": "token"})
    assert await client.exchange_code("code") == "token"

    http.get.return_value = response(
        200,
        {
            "id": "1130000",
            "login": "student",
            "display_name": "Студент",
            "default_email": "student@yandex.ru",
            "is_avatar_empty": False,
            "default_avatar_id": "abc",
        },
    )
    profile = await client.fetch_profile("token")

    assert profile.provider_id == "1130000"
    assert profile.email == "student@yandex.ru"
    assert profile.name == "Студент"
    assert profile.avatar_url == "https://avatars.yandex.net/get-yapic/abc/islands-200"


async def test_yandex_profile_without_avatar_and_display_name() -> None:
    http = cast(Any, type("HttpFake", (), {"post": AsyncMock(), "get": AsyncMock()})())
    client = YandexOAuthClient(yandex_settings(), http)

    http.get.return_value = response(
        200,
        {"id": "7", "login": "s", "real_name": "Реальное Имя", "is_avatar_empty": True},
    )
    profile = await client.fetch_profile("token")

    assert profile.avatar_url is None
    assert profile.name == "Реальное Имя"
    assert profile.email is None


async def test_yandex_rejects_profile_without_id_and_missing_token() -> None:
    http = cast(Any, type("HttpFake", (), {"post": AsyncMock(), "get": AsyncMock()})())
    client = YandexOAuthClient(yandex_settings(), http)

    http.get.return_value = response(200, {"login": "s"})
    with pytest.raises(OAuthProviderError, match="id или login"):
        await client.fetch_profile("token")

    http.post.return_value = response(200, {"error": "invalid_grant"})
    with pytest.raises(OAuthProviderError, match="access-токен"):
        await client.exchange_code("bad")


def gitlab_settings() -> Settings:
    return Settings(
        _env_file=None,
        jwt_secret=TEST_SECRET,
        github_client_id="cid",
        github_client_secret=SecretStr("csecret"),
        gitlab_client_id="lcid",
        gitlab_client_secret=SecretStr("lsecret"),
    )


async def test_gitlab_client_reads_profile_and_exchanges_code() -> None:
    http = cast(Any, type("HttpFake", (), {"post": AsyncMock(), "get": AsyncMock()})())
    client = GitLabOAuthClient(gitlab_settings(), http)
    assert "state=state" in client.authorize_url("state")
    assert "response_type=code" in client.authorize_url("state")

    http.post.return_value = response(200, {"access_token": "token"})
    assert await client.exchange_code("code") == "token"

    http.get.return_value = response(
        200,
        {
            "id": 42,
            "username": "student",
            "name": "Студент",
            "email": "student@example.test",
            "avatar_url": "https://example.test/a.png",
        },
    )
    profile = await client.fetch_profile("token")

    assert profile.provider_id == "42"
    assert profile.login == "student"
    assert profile.email == "student@example.test"
    assert profile.avatar_url == "https://example.test/a.png"


async def test_gitlab_rejects_profile_without_id_and_missing_token() -> None:
    http = cast(Any, type("HttpFake", (), {"post": AsyncMock(), "get": AsyncMock()})())
    client = GitLabOAuthClient(gitlab_settings(), http)

    http.get.return_value = response(200, {"username": "s"})
    with pytest.raises(OAuthProviderError, match="id или username"):
        await client.fetch_profile("token")

    http.post.return_value = response(200, {"error": "invalid_grant"})
    with pytest.raises(OAuthProviderError, match="access-токен"):
        await client.exchange_code("bad")


async def test_github_exchange_rejects_missing_token(settings: Settings) -> None:
    http = cast(Any, type("HttpFake", (), {"post": AsyncMock(return_value=response(200, {}))})())
    with pytest.raises(OAuthProviderError, match="access-токен"):
        await GitHubOAuthClient(settings, http).exchange_code("bad")


async def test_redis_namespace_and_oauth_state(settings: Settings) -> None:
    redis = cast(
        Any,
        type(
            "RedisFake",
            (),
            {
                "set": AsyncMock(),
                "get": AsyncMock(return_value=b"value"),
                "getdel": AsyncMock(return_value="once"),
                "delete": AsyncMock(),
            },
        )(),
    )
    namespace = RedisNamespace(redis, "prefix:", timedelta(seconds=10))
    assert namespace.key("key") == "prefix:key"
    await namespace.put("key", "value")
    await namespace.put("key", "value", timedelta(seconds=2))
    assert await namespace.get("key") == "value"
    assert await namespace.take("key") == "once"
    await namespace.drop("key")
    assert _decode(None) is None

    store = OAuthStateStore(redis, settings)
    state = OAuthState(provider=IdentityProvider.GITHUB, purpose="login")
    token = await store.issue(state)
    raw = redis.set.await_args.args[1]
    redis.getdel.return_value = raw
    consumed = await store.consume(token)
    assert consumed == state
    assert consumed is not None
    assert consumed.provider is IdentityProvider.GITHUB
    redis.getdel.return_value = None
    assert await store.consume(token) is None


async def test_s3_storage_maps_sdk_errors() -> None:
    client = cast(
        Any,
        type(
            "S3Fake",
            (),
            {"put_object": AsyncMock(), "delete_object": AsyncMock()},
        )(),
    )
    storage = S3Storage(client, "bucket", "https://assets.test")
    assert storage.public_url("key") == "https://assets.test/key"
    assert await storage.upload("key", b"body", AssetMime.PNG) == "https://assets.test/key"
    await storage.delete("key")

    client.put_object.side_effect = BotoCoreError()
    with pytest.raises(StorageError):
        await storage.upload("key", b"body", AssetMime.PNG)
    client.delete_object.side_effect = BotoCoreError()
    with pytest.raises(StorageError):
        await storage.delete("key")


def test_settings_helpers_and_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _parse_duration("15") == timedelta(seconds=15)
    assert _parse_duration("PT1M") == "PT1M"
    local = Settings(
        _env_file=None,
        jwt_secret="secret",  # noqa: S106
        github_client_id="id",
        github_client_secret="secret",  # noqa: S106
    )
    assert not local.is_production
    assert local.s3_public_base_url == "https://tramplin.s3.us-east-1.amazonaws.com"
    custom = Settings(
        _env_file=None,
        environment=Environment.PRODUCTION,
        jwt_secret="secret",  # noqa: S106
        github_client_id="id",
        github_client_secret="secret",  # noqa: S106
        s3_endpoint_url="https://s3.test/",
    )
    assert custom.is_production
    assert custom.s3_public_base_url == "https://s3.test/tramplin"
    custom.s3_public_url = "https://cdn.test/tramplin/"
    assert custom.s3_public_base_url == "https://cdn.test/tramplin"
    monkeypatch.setenv("JWT_SECRET", "secret")
    monkeypatch.setenv("GITHUB_CLIENT_ID", "id")
    monkeypatch.setenv("GITHUB_CLIENT_SECRET", "secret")
    assert isinstance(load_settings(), Settings)
