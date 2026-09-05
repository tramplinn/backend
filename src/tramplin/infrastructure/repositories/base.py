from sqlalchemy.ext.asyncio import AsyncSession

from tramplin.models.base import SoftDeleteMixin, soft_delete


class Repository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add[T](self, entity: T) -> T:
        self._session.add(entity)
        return entity

    async def delete(self, entity: SoftDeleteMixin) -> None:
        soft_delete(entity)
