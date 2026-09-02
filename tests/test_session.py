import pytest

from tests.conftest import AuthEnv
from tests.test_oauth_auth import start_login
from tramplin.core.errors import InvalidTokenError, UserInactiveError


async def test_refresh_rotates_token_and_invalidates_previous(env: AuthEnv) -> None:
    result = await env.github.complete_callback("code", await start_login(env.github))
    old_token = result.tokens.refresh_token

    rotated = await env.sessions.refresh(old_token)

    assert rotated.refresh_token != old_token
    assert len(env.refresh_tokens.tokens) == 1
    with pytest.raises(InvalidTokenError):
        await env.sessions.refresh(old_token)


async def test_refresh_with_unknown_token_raises_invalid_token(env: AuthEnv) -> None:
    with pytest.raises(InvalidTokenError):
        await env.sessions.refresh("never-issued")


async def test_logout_removes_only_the_used_refresh_token(env: AuthEnv) -> None:
    first = await env.github.complete_callback("code", await start_login(env.github))
    second = await env.github.complete_callback("code", await start_login(env.github))

    await env.sessions.logout(first.tokens.refresh_token)

    assert len(env.refresh_tokens.tokens) == 1
    with pytest.raises(InvalidTokenError):
        await env.sessions.refresh(first.tokens.refresh_token)
    assert await env.sessions.refresh(second.tokens.refresh_token) is not None


async def test_logout_everywhere_removes_all_user_tokens(env: AuthEnv) -> None:
    result = await env.github.complete_callback("code", await start_login(env.github))
    await env.github.complete_callback("code", await start_login(env.github))

    removed = await env.sessions.logout_everywhere(result.user.id)

    assert removed == 2
    assert env.refresh_tokens.tokens == []


async def test_authenticate_returns_user_for_valid_access_token(env: AuthEnv) -> None:
    result = await env.github.complete_callback("code", await start_login(env.github))

    user = await env.sessions.authenticate(result.tokens.access_token)

    assert user.id == result.user.id


async def test_authenticate_rejects_tampered_access_token(env: AuthEnv) -> None:
    result = await env.github.complete_callback("code", await start_login(env.github))

    with pytest.raises(InvalidTokenError):
        await env.sessions.authenticate(result.tokens.access_token + "x")


async def test_authenticate_rejects_token_of_disabled_user(env: AuthEnv) -> None:
    result = await env.github.complete_callback("code", await start_login(env.github))
    result.user.is_active = False

    with pytest.raises(UserInactiveError):
        await env.sessions.authenticate(result.tokens.access_token)
