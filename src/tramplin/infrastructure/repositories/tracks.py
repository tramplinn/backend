from collections.abc import Sequence

import uuid_utils.compat as uuid
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from tramplin.infrastructure.repositories.base import Repository
from tramplin.models.content import Course, Track, TrackCourse
from tramplin.models.enums import ContentStatus


class TrackRepository(Repository):
    async def list(
        self,
        *,
        published_only: bool,
        limit: int,
        offset: int,
    ) -> tuple[list[Track], int]:
        stmt = (
            select(Track)
            .order_by(Track.title)
            .options(
                selectinload(Track.courses)
                .selectinload(TrackCourse.course)
                .selectinload(Course.cover_asset),
                selectinload(Track.courses)
                .selectinload(TrackCourse.course)
                .selectinload(Course.tags),
            )
        )
        count_stmt = select(func.count()).select_from(Track)
        if published_only:
            stmt = stmt.where(Track.status == ContentStatus.PUBLISHED)
            count_stmt = count_stmt.where(Track.status == ContentStatus.PUBLISHED)
        total = await self._session.scalar(count_stmt)
        items = await self._session.scalars(stmt.limit(limit).offset(offset))
        return list(items), total or 0

    async def get(self, track_id: uuid.UUID) -> Track | None:
        stmt = (
            select(Track)
            .where(Track.id == track_id)
            .options(
                selectinload(Track.courses)
                .selectinload(TrackCourse.course)
                .selectinload(Course.cover_asset),
                selectinload(Track.courses)
                .selectinload(TrackCourse.course)
                .selectinload(Course.tags),
            )
        )
        return (await self._session.scalars(stmt)).one_or_none()

    async def get_for_update(self, track_id: uuid.UUID) -> Track | None:
        stmt = select(Track).where(Track.id == track_id).with_for_update()
        return (await self._session.scalars(stmt)).one_or_none()

    async def get_by_slug(self, slug: str, *, published_only: bool) -> Track | None:
        stmt = (
            select(Track)
            .where(Track.slug == slug)
            .options(
                selectinload(Track.courses)
                .selectinload(TrackCourse.course)
                .selectinload(Course.cover_asset),
                selectinload(Track.courses)
                .selectinload(TrackCourse.course)
                .selectinload(Course.tags),
            )
        )
        if published_only:
            stmt = stmt.where(Track.status == ContentStatus.PUBLISHED)
        return (await self._session.scalars(stmt)).one_or_none()

    async def get_course_link(
        self,
        track_id: uuid.UUID,
        course_id: uuid.UUID,
    ) -> TrackCourse | None:
        return await self._session.get(TrackCourse, (track_id, course_id))

    async def list_course_links(self, track_id: uuid.UUID) -> Sequence[TrackCourse]:
        stmt = (
            select(TrackCourse)
            .where(TrackCourse.track_id == track_id)
            .order_by(TrackCourse.position)
        )
        return list(await self._session.scalars(stmt))

    def add_course_link(self, link: TrackCourse) -> TrackCourse:
        self._session.add(link)
        return link

    async def delete_course_link(self, link: TrackCourse) -> None:
        await self._session.delete(link)
