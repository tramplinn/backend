from typing import Protocol

import uuid_utils.compat as uuid

from tramplin.core.errors import NotFoundError, UnprocessableError
from tramplin.models.users import StudentGroup
from tramplin.services.contracts import Transaction
from tramplin.services.entity_updates import mark_created


class GroupRepositoryPort(Protocol):
    async def list(self) -> list[StudentGroup]: ...

    async def get(self, group_id: uuid.UUID) -> StudentGroup | None: ...

    def add(self, group: StudentGroup) -> StudentGroup: ...

    async def delete(self, group: StudentGroup) -> None: ...


class GroupService:
    def __init__(self, transaction: Transaction, groups: GroupRepositoryPort) -> None:
        self._transaction = transaction
        self._groups = groups

    async def list(self) -> list[StudentGroup]:
        return await self._groups.list()

    async def create(self, group: StudentGroup, actor_id: uuid.UUID) -> StudentGroup:
        mark_created(group, actor_id)
        self._groups.add(group)
        await self._transaction.commit()
        return group

    async def update(
        self,
        group_id: uuid.UUID,
        changes: dict[str, str | int | None],
        actor_id: uuid.UUID,
    ) -> StudentGroup:
        group = await self._groups.get(group_id)
        if group is None:
            raise NotFoundError("Учебная группа не найдена")
        for field, value in changes.items():
            if value is None:
                raise UnprocessableError(f"Поле {field} не может быть null")
            setattr(group, field, value)
        group.updated_by = actor_id
        await self._transaction.commit()
        return group

    async def delete(self, group_id: uuid.UUID) -> None:
        group = await self._groups.get(group_id)
        if group is None:
            raise NotFoundError("Учебная группа не найдена")
        await self._groups.delete(group)
        await self._transaction.commit()
