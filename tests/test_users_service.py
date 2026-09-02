import pytest

from tests.conftest import AuthEnv
from tests.test_oauth_auth import start_login
from tramplin.core.errors import ConflictError, ForbiddenError, NotFoundError
from tramplin.models.enums import IdentityProvider, UserRole
from tramplin.models.users import User
from tramplin.services.users import ensure_role


async def test_get_profile_returns_user_with_identities(env: AuthEnv) -> None:
    result = await env.github.complete_callback("code", await start_login(env.github))

    profile = await env.users_service.get_profile(result.user.id)

    assert profile.id == result.user.id
    assert profile.login == "student-one"


async def test_unlink_last_identity_is_rejected(env: AuthEnv) -> None:
    result = await env.github.complete_callback("code", await start_login(env.github))

    with pytest.raises(ConflictError):
        await env.users_service.unlink_identity(result.user.id, IdentityProvider.GITHUB)


async def test_unlink_identity_that_is_not_linked_raises_not_found(env: AuthEnv) -> None:
    user = await env.github.complete_callback("code", await start_login(env.github))
    env.identities.identities.clear()

    with pytest.raises(NotFoundError):
        await env.users_service.unlink_identity(user.user.id, IdentityProvider.GITHUB)


@pytest.mark.parametrize(
    ("role", "minimum", "allowed"),
    [
        (UserRole.STUDENT, UserRole.STUDENT, True),
        (UserRole.STUDENT, UserRole.TEACHER, False),
        (UserRole.STUDENT, UserRole.ADMIN, False),
        (UserRole.TEACHER, UserRole.TEACHER, True),
        (UserRole.TEACHER, UserRole.ADMIN, False),
        (UserRole.ADMIN, UserRole.TEACHER, True),
        (UserRole.ADMIN, UserRole.ADMIN, True),
    ],
)
def test_ensure_role_allows_only_equal_or_higher_role(
    role: UserRole,
    minimum: UserRole,
    allowed: bool,
) -> None:
    user = User(login="someone", role=role, is_active=True)

    if allowed:
        ensure_role(user, minimum)
    else:
        with pytest.raises(ForbiddenError):
            ensure_role(user, minimum)
