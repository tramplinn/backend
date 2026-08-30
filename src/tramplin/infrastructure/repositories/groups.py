import uuid_utils.compat as uuid
from sqlalchemy import select

from tramplin.infrastructure.repositories.base import Repository
from tramplin.models.users import StudentGroup


class GroupRepository(Repository):
    async def list(self) -> list[StudentGroup]:
        stmt = select(StudentGroup).order_by(StudentGroup.year.desc(), StudentGroup.name)
        return list(await self._session.scalars(stmt))

    async def get(self, group_id: uuid.UUID) -> StudentGroup | None:
        return await self._session.get(StudentGroup, group_id)

    def add(self, group: StudentGroup) -> StudentGroup:
        self._session.add(group)
        return group

    async def delete(self, group: StudentGroup) -> None:
        await self._session.delete(group)
