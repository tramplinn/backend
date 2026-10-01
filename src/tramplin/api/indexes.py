"""Компактные несписочные индексы для агентов: все сущности одним ответом, без пагинации."""

from collections.abc import Awaitable, Callable

import uuid_utils.compat as uuid
from pydantic import Field

from tramplin.api.schemas.base import ApiModel
from tramplin.models.enums import AlgorithmDifficulty, ContentStatus
from tramplin.services.contracts import PageResult

INDEX_PAGE_SIZE = 200


class IndexItemOut(ApiModel):
    id: uuid.UUID
    slug: str
    title: str
    status: ContentStatus


class ProblemIndexItemOut(IndexItemOut):
    difficulty: AlgorithmDifficulty


class IndexOut[T: IndexItemOut](ApiModel):
    items: list[T]
    total: int = Field(description="Всего сущностей; items всегда содержит их все.")


async def fetch_all[T](fetch: Callable[[int, int], Awaitable[PageResult[T]]]) -> list[T]:
    items: list[T] = []
    while True:
        page = await fetch(INDEX_PAGE_SIZE, len(items))
        items.extend(page.items)
        if not page.items or len(items) >= page.total:
            return items
