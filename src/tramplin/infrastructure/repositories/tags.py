from collections.abc import Sequence

from sqlalchemy import func, select

from tramplin.infrastructure.repositories.base import Repository
from tramplin.models.tags import Tag


class TagRepository(Repository):
    async def list_all(self) -> list[Tag]:
        stmt = select(Tag).order_by(Tag.name)
        return list(await self._session.scalars(stmt))

    async def get_or_create_many(self, names: Sequence[str]) -> list[Tag]:
        """Сохраняет порядок первого появления, дедуп и поиск существующих — без учёта регистра."""
        resolved: list[Tag] = []
        seen: set[str] = set()
        for raw in names:
            name = raw.strip()
            if not name:
                continue
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            tag = await self._get_by_lower_name(key)
            if tag is None:
                tag = Tag(name=name)
                self.add(tag)
            resolved.append(tag)
        return resolved

    async def _get_by_lower_name(self, lower_name: str) -> Tag | None:
        stmt = select(Tag).where(func.lower(Tag.name) == lower_name)
        return (await self._session.scalars(stmt)).one_or_none()
