from urllib.parse import parse_qs, urlparse

import pytest
import uuid_utils.compat as uuid

from tests.conftest import AuthEnv
from tramplin.core.errors import (
    IdentityAlreadyLinkedError,
    NotFoundError,
    OAuthStateError,
    UserInactiveError,
)
from tramplin.models.enums import IdentityProvider, UserRole
from tramplin.models.users import User
from tramplin.services.contracts import OAuthProfile
from tramplin.services.oauth_auth import OAuthAuthService, OAuthRegistry


async def start_login(github: OAuthAuthService) -> str:
    """Возвращает state-токен, выданный при старте OAuth: фейк кладёт его в query."""
    url = await github.start_login()
    return parse_qs(urlparse(url).query)["state"][0]


async def start_link(github: OAuthAuthService, user_id: uuid.UUID) -> str:
    url = await github.start_link(user_id)
    return parse_qs(urlparse(url).query)["state"][0]


async def test_callback_for_new_profile_creates_user_and_identity(env: AuthEnv) -> None:
    result = await env.github.complete_callback("code", await start_login(env.github))

    assert len(env.users.users) == 1
    assert result.user.login == "student-one"
    assert env.identities.identities[0].provider is IdentityProvider.GITHUB
    assert env.identities.identities[0].provider_id == "42"
    assert len(env.refresh_tokens.tokens) == 1


async def test_callback_for_known_identity_reuses_existing_user(env: AuthEnv) -> None:
    first = await env.github.complete_callback("code", await start_login(env.github))

    second = await env.github.complete_callback("code", await start_login(env.github))

    assert first.user.id == second.user.id
    assert len(env.users.users) == 1


async def test_callback_with_same_email_does_not_link_accounts_automatically(
    env: AuthEnv,
    github_profile: OAuthProfile,
) -> None:
    existing = env.users.add(
        User(login="existing", email=github_profile.email, role=UserRole.STUDENT, is_active=True),
    )

    result = await env.github.complete_callback("code", await start_login(env.github))

    assert result.user.id != existing.id
    assert len(env.users.users) == 2
    assert [i.user_id for i in env.identities.identities] == [result.user.id]


async def test_callback_with_unknown_state_raises_oauth_state_error(env: AuthEnv) -> None:
    with pytest.raises(OAuthStateError):
        await env.github.complete_callback("code", "state-unknown")


async def test_callback_state_is_single_use(env: AuthEnv) -> None:
    state = await start_login(env.github)
    await env.github.complete_callback("code", state)

    with pytest.raises(OAuthStateError):
        await env.github.complete_callback("code", state)


async def test_callback_for_inactive_user_raises_user_inactive(env: AuthEnv) -> None:
    result = await env.github.complete_callback("code", await start_login(env.github))
    result.user.is_active = False

    with pytest.raises(UserInactiveError):
        await env.github.complete_callback("code", await start_login(env.github))


async def test_link_flow_attaches_identity_to_logged_in_user(env: AuthEnv) -> None:
    user = env.users.add(User(login="teacher", role=UserRole.TEACHER, is_active=True))

    result = await env.github.complete_callback("code", await start_link(env.github, user.id))

    assert result.user.id == user.id
    assert len(env.users.users) == 1
    assert env.identities.identities[0].user_id == user.id


async def test_link_flow_fills_empty_avatar_from_provider(env: AuthEnv) -> None:
    user = env.users.add(User(login="teacher", role=UserRole.TEACHER, is_active=True))

    result = await env.github.complete_callback("code", await start_link(env.github, user.id))

    assert result.user.avatar_url == "https://avatars.test/42.png"


async def test_link_flow_does_not_overwrite_existing_avatar(env: AuthEnv) -> None:
    user = env.users.add(
        User(
            login="teacher",
            role=UserRole.TEACHER,
            is_active=True,
            avatar_url="https://example.com/custom.png",
        )
    )

    result = await env.github.complete_callback("code", await start_link(env.github, user.id))

    assert result.user.avatar_url == "https://example.com/custom.png"


async def test_link_flow_for_identity_owned_by_another_user_raises_conflict(env: AuthEnv) -> None:
    await env.github.complete_callback("code", await start_login(env.github))
    other = env.users.add(User(login="other", role=UserRole.STUDENT, is_active=True))

    with pytest.raises(IdentityAlreadyLinkedError):
        await env.github.complete_callback("code", await start_link(env.github, other.id))


async def test_registry_serves_configured_provider_and_refuses_unknown(env: AuthEnv) -> None:
    registry = OAuthRegistry([env.github])

    assert registry.available == [IdentityProvider.GITHUB]
    assert registry.get(IdentityProvider.GITHUB) is env.github
    with pytest.raises(NotFoundError, match="не настроен"):
        registry.get(IdentityProvider.YANDEX)
