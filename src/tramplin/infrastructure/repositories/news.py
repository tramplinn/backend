import uuid_utils.compat as uuid
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from tramplin.infrastructure.repositories.base import Repository
from tramplin.models.enums import ContentStatus
from tramplin.models.news import News, NewsPhoto


class NewsRepository(Repository):
    _photos = selectinload(News.photos).selectinload(NewsPhoto.asset)

    async def list(
        self,
        *,
        published_only: bool,
        limit: int,
        offset: int,
    ) -> tuple[list[News], int]:
        stmt = select(News).options(self._photos)
        count_stmt = select(func.count()).select_from(News)
        if published_only:
            stmt = stmt.where(News.status == ContentStatus.PUBLISHED)
            count_stmt = count_stmt.where(News.status == ContentStatus.PUBLISHED)
        total = await self._session.scalar(count_stmt)
        # Черновики ещё без даты публикации, поэтому в редакторской ленте
        # они идут первыми: их и правят.
        stmt = stmt.order_by(News.published_at.desc().nullsfirst(), News.id.desc())
        items = await self._session.scalars(stmt.limit(limit).offset(offset))
        return list(items), total or 0

    async def get(self, news_id: uuid.UUID) -> News | None:
        stmt = select(News).where(News.id == news_id).options(self._photos)
        return (await self._session.scalars(stmt)).one_or_none()

    async def get_by_slug(self, slug: str, *, published_only: bool) -> News | None:
        stmt = select(News).where(News.slug == slug).options(self._photos)
        if published_only:
            stmt = stmt.where(News.status == ContentStatus.PUBLISHED)
        return (await self._session.scalars(stmt)).one_or_none()
