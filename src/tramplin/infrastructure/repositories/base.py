from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from tramplin.models.base import UUIDPrimaryKey


class Repository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add[T](self, entity: T) -> T:
        self._session.add(entity)
        return entity

    async def delete(self, entity: UUIDPrimaryKey) -> None:
        # DELETE по id, а не session.delete(): дочерние сущности снимаются каскадом
        # на уровне БД (FK ondelete="CASCADE"), без подгрузки ORM-связей.
        cls = type(entity)
        await self._session.execute(delete(cls).where(cls.id == entity.id))
