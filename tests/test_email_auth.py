from dataclasses import dataclass

import pytest
from pydantic import SecretStr

from tests.conftest import TEST_SECRET
from tests.fakes import (
    FakeEmailCodeStore,
    FakeEmailJobRepository,
    FakeEmailRenderer,
    FakeIdentityRepository,
    FakeRefreshTokenRepository,
    FakeSession,
    FakeUserRepository,
)
from tramplin.core.config import Settings
from tramplin.core.errors import (
    ConflictError,
    IdentityAlreadyLinkedError,
    InvalidEmailCodeError,
    TooManyRequestsError,
    UserInactiveError,
)
from tramplin.core.security import AccessTokenCodec
from tramplin.models.enums import IdentityProvider, UserRole
from tramplin.models.users import User
from tramplin.services.email_auth import EmailAuthService
from tramplin.services.session import SessionService


@dataclass(slots=True)
class EmailEnv:
    service: EmailAuthService
    users: FakeUserRepository
    identities: FakeIdentityRepository
    jobs: FakeEmailJobRepository


@pytest.fixture
def email_auth() -> EmailEnv:
    settings = Settings(
        _env_file=None,
        jwt_secret=TEST_SECRET,
        github_client_id="cid",
        github_client_secret=SecretStr("csecret"),
    )
    session = FakeSession()
    users = FakeUserRepository()
    identities = FakeIdentityRepository(users.users)
    jobs = FakeEmailJobRepository()
    sessions = SessionService(
        session=session,
        users=users,
        refresh_tokens=FakeRefreshTokenRepository(),
        codec=AccessTokenCodec(settings),
        settings=settings,
    )
    service = EmailAuthService(
        session=session,
        users=users,
        identities=identities,
        jobs=jobs,
        codes=FakeEmailCodeStore(),
        renderer=FakeEmailRenderer(),
        sessions=sessions,
        settings=settings,
    )
    return EmailEnv(service=service, users=users, identities=identities, jobs=jobs)


async def test_request_login_code_queues_a_rendered_email(email_auth: EmailEnv) -> None:
    await email_auth.service.request_login_code("Student@Example.com")

    assert len(email_auth.jobs.jobs) == 1
    job = email_auth.jobs.jobs[0]
    assert job.to_email == "student@example.com"
    assert job.category == "auth_otp"
    assert "000000" in job.text_body


async def test_verify_login_code_registers_new_user_on_first_login(email_auth: EmailEnv) -> None:
    await email_auth.service.request_login_code("student@example.com")
    result = await email_auth.service.verify_login_code("student@example.com", "000000")

    assert result.user.email == "student@example.com"
    assert result.user.login == "student"
    assert len(email_auth.users.users) == 1
    assert email_auth.identities.identities[0].provider is IdentityProvider.EMAIL


async def test_verify_login_code_logs_in_existing_identity(email_auth: EmailEnv) -> None:
    await email_auth.service.request_login_code("student@example.com")
    first = await email_auth.service.verify_login_code("student@example.com", "000000")

    await email_auth.service.request_login_code("student@example.com")
    second = await email_auth.service.verify_login_code("student@example.com", "000000")

    assert second.user.id == first.user.id
    assert len(email_auth.users.users) == 1


async def test_verify_login_code_rejects_wrong_code(email_auth: EmailEnv) -> None:
    await email_auth.service.request_login_code("student@example.com")

    with pytest.raises(InvalidEmailCodeError):
        await email_auth.service.verify_login_code("student@example.com", "111111")


async def test_verify_login_code_rejects_inactive_user(email_auth: EmailEnv) -> None:
    await email_auth.service.request_login_code("student@example.com")
    result = await email_auth.service.verify_login_code("student@example.com", "000000")
    email_auth.users.users[result.user.id].is_active = False

    await email_auth.service.request_login_code("student@example.com")
    with pytest.raises(UserInactiveError):
        await email_auth.service.verify_login_code("student@example.com", "000000")


async def test_request_login_code_respects_cooldown(email_auth: EmailEnv) -> None:
    await email_auth.service.request_login_code("student@example.com")

    with pytest.raises(TooManyRequestsError):
        await email_auth.service.request_login_code("student@example.com")


async def test_link_code_is_scoped_to_the_requesting_user(email_auth: EmailEnv) -> None:
    """Код на link привязан к user_id: другой пользователь не может его подтвердить —
    иначе чужая почта могла бы прилипнуть не к тому аккаунту."""
    owner = email_auth.users.add(User(login="owner", role=UserRole.STUDENT, is_active=True))
    intruder = email_auth.users.add(User(login="intruder", role=UserRole.STUDENT, is_active=True))

    await email_auth.service.request_link_code(owner.id, "new@example.com")

    with pytest.raises(InvalidEmailCodeError):
        await email_auth.service.verify_link_code(intruder.id, "new@example.com", "000000")

    linked = await email_auth.service.verify_link_code(owner.id, "new@example.com", "000000")
    assert linked.id == owner.id


async def test_link_code_rejects_identity_already_owned_by_another_user(
    email_auth: EmailEnv,
) -> None:
    first = email_auth.users.add(User(login="first", role=UserRole.STUDENT, is_active=True))
    second = email_auth.users.add(User(login="second", role=UserRole.STUDENT, is_active=True))

    await email_auth.service.request_link_code(first.id, "shared@example.com")
    await email_auth.service.verify_link_code(first.id, "shared@example.com", "000000")

    await email_auth.service.request_link_code(second.id, "shared@example.com")
    with pytest.raises(IdentityAlreadyLinkedError):
        await email_auth.service.verify_link_code(second.id, "shared@example.com", "000000")


async def test_link_code_rejects_second_email_for_same_user(email_auth: EmailEnv) -> None:
    user = email_auth.users.add(User(login="user", role=UserRole.STUDENT, is_active=True))

    await email_auth.service.request_link_code(user.id, "first@example.com")
    await email_auth.service.verify_link_code(user.id, "first@example.com", "000000")

    await email_auth.service.request_link_code(user.id, "second@example.com")
    with pytest.raises(ConflictError):
        await email_auth.service.verify_link_code(user.id, "second@example.com", "000000")
