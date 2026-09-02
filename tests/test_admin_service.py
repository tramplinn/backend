import pytest

from tests.fakes import FakeIdentityRepository, FakeSession, FakeUserRepository
from tramplin.core.errors import ConflictError
from tramplin.models.enums import UserRole
from tramplin.models.users import User
from tramplin.services.users import UserService


async def test_admin_cannot_disable_self() -> None:
    user = User(login="admin", role=UserRole.ADMIN, is_active=True)
    users = FakeUserRepository()
    users.add(user)
    service = UserService(
        FakeSession(),
        users,
        FakeIdentityRepository(users.users),
    )

    with pytest.raises(ConflictError):
        await service.update(user.id, user.id, {"is_active": False})


async def test_user_list_filters_and_paginates() -> None:
    users = FakeUserRepository()
    users.add(User(login="active-student", role=UserRole.STUDENT, is_active=True))
    users.add(User(login="inactive-student", role=UserRole.STUDENT, is_active=False))
    users.add(User(login="teacher", role=UserRole.TEACHER, is_active=True))
    service = UserService(
        FakeSession(),
        users,
        FakeIdentityRepository(users.users),
    )

    page = await service.list(
        query="student",
        role=UserRole.STUDENT,
        is_active=True,
        limit=1,
    )

    assert [user.login for user in page.items] == ["active-student"]
    assert page.total == 1
    assert page.limit == 1
