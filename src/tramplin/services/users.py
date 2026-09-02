from typing import Any, Final, Protocol

import uuid_utils.compat as uuid

from tramplin.core.errors import ConflictError, ForbiddenError, NotFoundError, UserInactiveError
from tramplin.models.enums import IdentityProvider, UserRole
from tramplin.models.users import User, UserIdentity
from tramplin.services.contracts import PageResult, Transaction


class UserRepositoryPort(Protocol):
    async def list(
        self,
        *,
        query: str | None,
        role: UserRole | None,
        is_active: bool | None,
        limit: int,
        offset: int,
    ) -> tuple[list[User], int]: ...

    async def get(self, user_id: uuid.UUID) -> User | None: ...

    async def get_with_identities(self, user_id: uuid.UUID) -> User | None: ...

    async def login_exists(self, login: str) -> bool: ...

    def add(self, user: User) -> User: ...


class UserIdentityRepositoryPort(Protocol):
    async def get_by_provider(
        self,
        provider: IdentityProvider,
        provider_id: str,
    ) -> UserIdentity | None: ...

    async def get_for_user(
        self,
        user_id: uuid.UUID,
        provider: IdentityProvider,
    ) -> UserIdentity | None: ...

    async def list_for_user(self, user_id: uuid.UUID) -> list[UserIdentity]: ...

    def add(self, identity: UserIdentity) -> UserIdentity: ...

    async def delete(self, identity: UserIdentity) -> None: ...


ROLE_RANK: Final[dict[UserRole, int]] = {
    UserRole.STUDENT: 0,
    UserRole.TEACHER: 1,
    UserRole.ADMIN: 2,
}


def ensure_active(user: User) -> None:
    if not user.is_active:
        raise UserInactiveError


def ensure_role(user: User, minimum: UserRole) -> None:
    """Роли иерархичны: admin проходит везде, куда пускают teacher, и так далее вниз."""
    if ROLE_RANK[user.role] < ROLE_RANK[minimum]:
        raise ForbiddenError


class UserService:
    def __init__(
        self,
        session: Transaction,
        users: UserRepositoryPort,
        identities: UserIdentityRepositoryPort,
    ) -> None:
        self._session = session
        self._users = users
        self._identities = identities

    async def list(
        self,
        *,
        query: str | None = None,
        role: UserRole | None = None,
        is_active: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> PageResult[User]:
        items, total = await self._users.list(
            query=query,
            role=role,
            is_active=is_active,
            limit=limit,
            offset=offset,
        )
        return PageResult(items=items, total=total, limit=limit, offset=offset)

    async def get_profile(self, user_id: uuid.UUID) -> User:
        user = await self._users.get_with_identities(user_id)
        if user is None:
            raise NotFoundError("Пользователь не найден")
        return user

    async def unlink_identity(self, user_id: uuid.UUID, provider: IdentityProvider) -> None:
        identities = await self._identities.list_for_user(user_id)
        target = next((i for i in identities if i.provider == provider), None)
        if target is None:
            raise NotFoundError("Такой способ входа не привязан")
        if len(identities) == 1:
            raise ConflictError("Нельзя отвязать единственный способ входа")
        await self._identities.delete(target)
        await self._session.commit()

    async def update(
        self,
        actor_id: uuid.UUID,
        user_id: uuid.UUID,
        changes: dict[str, Any],
    ) -> User:
        user = await self._users.get(user_id)
        if user is None:
            raise NotFoundError("Пользователь не найден")
        if user_id == actor_id and (
            changes.get("is_active") is False
            or changes.get("role") in {UserRole.STUDENT, UserRole.TEACHER}
        ):
            raise ConflictError("Нельзя отключить себя или снять с себя роль администратора")
        if "role" in changes:
            if changes["role"] is None:
                raise ConflictError("Поле role не может быть null")
            user.role = changes["role"]
        if "is_active" in changes:
            if changes["is_active"] is None:
                raise ConflictError("Поле is_active не может быть null")
            user.is_active = changes["is_active"]
        user.updated_by = actor_id
        await self._session.commit()
        return user
