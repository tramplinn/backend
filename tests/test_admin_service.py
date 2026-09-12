import pytest

from tests.fakes import (
    FakeAssetRepository,
    FakeCompanyRepository,
    FakeIdentityRepository,
    FakeInterestRepository,
    FakeSession,
    FakeUniversityRepository,
    FakeUserRepository,
)
from tramplin.core.errors import ConflictError
from tramplin.models.enums import UserRole
from tramplin.models.users import User
from tramplin.services.users import UserService


def _user_service(users: FakeUserRepository) -> UserService:
    return UserService(
        FakeSession(),
        users,
        FakeIdentityRepository(users.users),
        FakeCompanyRepository(),
        FakeUniversityRepository(),
        FakeInterestRepository(),
        FakeAssetRepository(),
    )


async def test_admin_cannot_disable_self() -> None:
    user = User(login="admin", role=UserRole.ADMIN, is_active=True)
    users = FakeUserRepository()
    users.add(user)
    service = _user_service(users)

    with pytest.raises(ConflictError):
        await service.update(user.id, user.id, {"is_active": False})


async def test_admin_update_changes_role_and_active_flag() -> None:
    admin = User(login="admin", role=UserRole.ADMIN, is_active=True)
    target = User(login="student", role=UserRole.STUDENT, is_active=True)
    users = FakeUserRepository()
    users.add(admin)
    users.add(target)
    service = _user_service(users)

    updated = await service.update(
        admin.id, target.id, {"role": UserRole.TEACHER, "is_active": False}
    )

    assert updated.role is UserRole.TEACHER
    assert updated.is_active is False


async def test_admin_update_rejects_null_role_and_active_flag() -> None:
    admin = User(login="admin", role=UserRole.ADMIN, is_active=True)
    target = User(login="student", role=UserRole.STUDENT, is_active=True)
    users = FakeUserRepository()
    users.add(admin)
    users.add(target)
    service = _user_service(users)

    with pytest.raises(ConflictError):
        await service.update(admin.id, target.id, {"role": None})
    with pytest.raises(ConflictError):
        await service.update(admin.id, target.id, {"is_active": None})


async def test_user_list_filters_and_paginates() -> None:
    users = FakeUserRepository()
    users.add(User(login="active-student", role=UserRole.STUDENT, is_active=True))
    users.add(User(login="inactive-student", role=UserRole.STUDENT, is_active=False))
    users.add(User(login="teacher", role=UserRole.TEACHER, is_active=True))
    service = _user_service(users)

    page = await service.list(
        query="student",
        role=UserRole.STUDENT,
        is_active=True,
        limit=1,
    )

    assert [user.login for user in page.items] == ["active-student"]
    assert page.total == 1
    assert page.limit == 1
