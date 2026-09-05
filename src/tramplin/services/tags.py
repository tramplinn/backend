from collections.abc import Sequence
from typing import Protocol

from tramplin.models.tags import Tag


class TagRepositoryPort(Protocol):
    async def list_all(self) -> list[Tag]: ...

    async def get_or_create_many(self, names: Sequence[str]) -> list[Tag]: ...


class TagService:
    def __init__(self, tags: TagRepositoryPort) -> None:
        self._tags = tags

    async def list_all(self) -> list[Tag]:
        return await self._tags.list_all()
