import uuid_utils.compat as uuid
from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from tramplin.infrastructure.repositories.base import Repository
from tramplin.models.enums import UserRole
from tramplin.models.users import User


class UserRepository(Repository):
    async def list(
        self,
        *,
        query: str | None,
        role: UserRole | None,
        group_id: uuid.UUID | None,
        is_active: bool | None,
        limit: int,
        offset: int,
    ) -> tuple[list[User], int]:
        filters = []
        if query:
            pattern = f"%{query}%"
            filters.append(
                or_(
                    User.login.ilike(pattern),
                    User.name.ilike(pattern),
                    User.email.ilike(pattern),
                    User.student_number.ilike(pattern),
                )
            )
        if role is not None:
            filters.append(User.role == role)
        if group_id is not None:
            filters.append(User.group_id == group_id)
        if is_active is not None:
            filters.append(User.is_active == is_active)

        count_stmt = select(func.count()).select_from(User).where(*filters)
        total = await self._session.scalar(count_stmt)
        stmt = select(User).where(*filters).order_by(User.login).limit(limit).offset(offset)
        return list(await self._session.scalars(stmt)), total or 0

    async def get(self, user_id: uuid.UUID) -> User | None:
        return await self._session.get(User, user_id)

    async def get_with_identities(self, user_id: uuid.UUID) -> User | None:
        stmt = select(User).where(User.id == user_id).options(selectinload(User.identities))
        return (await self._session.scalars(stmt)).one_or_none()

    async def login_exists(self, login: str) -> bool:
        stmt = select(User.id).where(User.login == login).limit(1)
        return (await self._session.scalars(stmt)).first() is not None

    def add(self, user: User) -> User:
        self._session.add(user)
        return user
