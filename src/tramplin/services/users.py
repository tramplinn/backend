from collections.abc import Sequence
from typing import Any, Final, Protocol

import uuid_utils.compat as uuid

from tramplin.core.errors import (
    ConflictError,
    ForbiddenError,
    InvalidUpdateError,
    NotFoundError,
    UserInactiveError,
)
from tramplin.models.assets import Asset
from tramplin.models.directories import Company, Interest, University
from tramplin.models.enums import AssetMime, IdentityProvider, UserRole
from tramplin.models.users import User, UserIdentity
from tramplin.services.contracts import CourseActivity, PageResult, ProfileStats, Transaction
from tramplin.services.entity_updates import require

SIMPLE_PROFILE_FIELDS = {"name", "headline", "bio", "specialty", "grade", "experience_years"}
type CourseActivities = list[CourseActivity]


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

    async def get_active_by_login(self, login: str) -> User | None: ...

    async def public_stats(self, user_id: uuid.UUID) -> ProfileStats: ...

    async def active_courses(self, user_id: uuid.UUID) -> CourseActivities: ...

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


class CompanyRepositoryPort(Protocol):
    async def get_or_create_one(self, name: str) -> Company: ...


class UniversityRepositoryPort(Protocol):
    async def get_or_create_one(self, name: str) -> University: ...


class InterestRepositoryPort(Protocol):
    async def get_or_create_many(self, names: Sequence[str]) -> list[Interest]: ...


class AssetRepositoryPort(Protocol):
    async def get(self, asset_id: uuid.UUID) -> Asset | None: ...


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
        companies: CompanyRepositoryPort,
        universities: UniversityRepositoryPort,
        interests: InterestRepositoryPort,
        assets: AssetRepositoryPort,
    ) -> None:
        self._session = session
        self._users = users
        self._identities = identities
        self._companies = companies
        self._universities = universities
        self._interests = interests
        self._assets = assets

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
        return require(
            await self._users.get_with_identities(user_id), NotFoundError("Пользователь не найден")
        )

    async def get_public_profile(
        self,
        login: str,
    ) -> tuple[User, ProfileStats, CourseActivities]:
        user = require(
            await self._users.get_active_by_login(login), NotFoundError("Пользователь не найден")
        )
        stats = await self._users.public_stats(user.id)
        courses = await self._users.active_courses(user.id)
        return user, stats, courses

    async def update_profile(self, user_id: uuid.UUID, changes: dict[str, Any]) -> User:
        user = require(await self._users.get(user_id), NotFoundError("Пользователь не найден"))
        for field, value in changes.items():
            if field in SIMPLE_PROFILE_FIELDS:
                setattr(user, field, value)
        if "company" in changes:
            user.company = await self._resolve_company(changes["company"])
        if "university" in changes:
            user.university = await self._resolve_university(changes["university"])
        if "interests" in changes:
            user.interests = await self._interests.get_or_create_many(changes["interests"] or [])
        if "resume_asset_id" in changes:
            resume_asset = await self._resolve_resume_asset(changes["resume_asset_id"])
            user.resume_asset = resume_asset
            user.resume_asset_id = resume_asset.id if resume_asset else None
        user.updated_by = user_id
        await self._session.commit()
        return await self.get_profile(user_id)

    async def _resolve_company(self, name: str | None) -> Company | None:
        if name is None or not name.strip():
            return None
        return await self._companies.get_or_create_one(name)

    async def _resolve_university(self, name: str | None) -> University | None:
        if name is None or not name.strip():
            return None
        return await self._universities.get_or_create_one(name)

    async def _resolve_resume_asset(self, asset_id: uuid.UUID | None) -> Asset | None:
        if asset_id is None:
            return None
        asset = require(await self._assets.get(asset_id), NotFoundError("Файл не найден"))
        if asset.mime is not AssetMime.PDF:
            raise InvalidUpdateError("Резюме должно быть в формате PDF")
        return asset

    async def unlink_identity(self, user_id: uuid.UUID, provider: IdentityProvider) -> None:
        identities = await self._identities.list_for_user(user_id)
        target = require(
            next((i for i in identities if i.provider == provider), None),
            NotFoundError("Такой способ входа не привязан"),
        )
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
        user = require(await self._users.get(user_id), NotFoundError("Пользователь не найден"))
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
        # Оба поля nullable: null — это очистка, а не ошибка.
        if "name" in changes:
            user.name = changes["name"]
        if "student_number" in changes:
            user.student_number = changes["student_number"]
        user.updated_by = actor_id
        await self._session.commit()
        return user
