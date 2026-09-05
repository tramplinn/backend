from collections.abc import Sequence
from datetime import datetime
from typing import Any, Protocol

import uuid_utils.compat as uuid

from tramplin.core.errors import InvalidUpdateError, NotFoundError
from tramplin.core.time import utc_now
from tramplin.models.enums import ContentStatus
from tramplin.models.news import News, NewsPhoto
from tramplin.services.assets import AssetRepositoryPort
from tramplin.services.contracts import PageResult, Transaction
from tramplin.services.entity_updates import (
    mark_created,
    mark_updated,
    require,
    validate_required_updates,
)

# В теле класса имя list занято методом NewsService.list, поэтому подпись
# _build_photos ссылается на псевдоним.
type NewsPhotos = list[NewsPhoto]


class NewsRepositoryPort(Protocol):
    async def list(
        self,
        *,
        published_only: bool,
        limit: int,
        offset: int,
    ) -> tuple[list[News], int]: ...

    async def get(self, news_id: uuid.UUID) -> News | None: ...

    async def get_by_slug(self, slug: str, *, published_only: bool) -> News | None: ...

    def add(self, news: News) -> News: ...

    async def delete(self, news: News) -> None: ...


class NewsService:
    def __init__(
        self,
        transaction: Transaction,
        news: NewsRepositoryPort,
        assets: AssetRepositoryPort,
    ) -> None:
        self._transaction = transaction
        self._news = news
        self._assets = assets

    async def list(
        self,
        *,
        published_only: bool = True,
        limit: int = 20,
        offset: int = 0,
    ) -> PageResult[News]:
        items, total = await self._news.list(
            published_only=published_only,
            limit=limit,
            offset=offset,
        )
        return PageResult(items=items, total=total, limit=limit, offset=offset)

    async def get(self, slug: str, *, published_only: bool = True) -> News:
        return require(
            await self._news.get_by_slug(slug, published_only=published_only),
            NotFoundError("Новость не найдена"),
        )

    async def create(
        self,
        news: News,
        actor_id: uuid.UUID,
        photo_ids: Sequence[uuid.UUID] = (),
    ) -> News:
        news.photos = await self._build_photos(photo_ids, actor_id)
        news.published_at = _published_at(news.status, None)
        mark_created(news, actor_id)
        self._news.add(news)
        await self._transaction.commit()
        return news

    async def update(
        self,
        news_id: uuid.UUID,
        changes: dict[str, Any],
        actor_id: uuid.UUID,
    ) -> News:
        news = require(await self._news.get(news_id), NotFoundError("Новость не найдена"))
        photo_ids = changes.pop("photo_ids", None)
        validate_required_updates(changes, {"title", "slug", "body_md", "status"})
        news.title = changes.get("title", news.title)
        news.slug = changes.get("slug", news.slug)
        news.summary = changes.get("summary", news.summary)
        news.body_md = changes.get("body_md", news.body_md)
        news.status = changes.get("status", news.status)
        news.published_at = _published_at(news.status, news.published_at)
        if photo_ids is not None:
            news.photos = await self._build_photos(photo_ids, actor_id)
        mark_updated(news, actor_id)
        await self._transaction.commit()
        return news

    async def delete(self, news_id: uuid.UUID) -> None:
        news = require(await self._news.get(news_id), NotFoundError("Новость не найдена"))
        await self._news.delete(news)
        await self._transaction.commit()

    async def _build_photos(
        self,
        asset_ids: Sequence[uuid.UUID],
        actor_id: uuid.UUID,
    ) -> NewsPhotos:
        """Позиция — это место в присланном списке: порядок галереи задаёт редактор."""
        if len(asset_ids) != len(set(asset_ids)):
            raise InvalidUpdateError("Фотографии не должны повторяться", field="photo_ids")
        photos: NewsPhotos = []
        for position, asset_id in enumerate(asset_ids):
            asset = require(
                await self._assets.get(asset_id), NotFoundError("Фотография не найдена")
            )
            photo = NewsPhoto(asset_id=asset.id, position=position)
            photo.asset = asset
            mark_created(photo, actor_id)
            photos.append(photo)
        return photos


def _published_at(status: ContentStatus, current: datetime | None) -> datetime | None:
    """Дата публикации живёт вместе со статусом: снятая с публикации новость
    возвращается в ленту тем же числом, что и была, а не датой правки."""
    if status is not ContentStatus.PUBLISHED:
        return current
    return current or utc_now()
