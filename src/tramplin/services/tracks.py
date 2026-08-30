from collections.abc import Sequence
from typing import Any, Protocol

import uuid_utils.compat as uuid

from tramplin.core.errors import NotFoundError
from tramplin.models.content import Track, TrackCourse
from tramplin.services.contracts import Transaction
from tramplin.services.courses import CourseRepositoryPort
from tramplin.services.entity_updates import (
    apply_changes,
    apply_order_by,
    mark_created,
    mark_updated,
)


class TrackRepositoryPort(Protocol):
    async def list(self, *, published_only: bool) -> list[Track]: ...

    async def get(self, track_id: uuid.UUID) -> Track | None: ...

    async def get_for_update(self, track_id: uuid.UUID) -> Track | None: ...

    async def get_by_slug(self, slug: str, *, published_only: bool) -> Track | None: ...

    def add(self, track: Track) -> Track: ...

    async def delete(self, track: Track) -> None: ...

    async def get_course_link(
        self,
        track_id: uuid.UUID,
        course_id: uuid.UUID,
    ) -> TrackCourse | None: ...

    async def list_course_links(self, track_id: uuid.UUID) -> Sequence[TrackCourse]: ...

    def add_course_link(self, link: TrackCourse) -> TrackCourse: ...

    async def delete_course_link(self, link: TrackCourse) -> None: ...


class TrackService:
    def __init__(
        self,
        transaction: Transaction,
        tracks: TrackRepositoryPort,
        courses: CourseRepositoryPort,
    ) -> None:
        self._transaction = transaction
        self._tracks = tracks
        self._courses = courses

    async def list(self, *, published_only: bool = True) -> list[Track]:
        return await self._tracks.list(published_only=published_only)

    async def get(self, slug: str, *, published_only: bool = True) -> Track:
        track = await self._tracks.get_by_slug(slug, published_only=published_only)
        if track is None:
            raise NotFoundError("Трек не найден")
        return track

    async def create(self, track: Track, actor_id: uuid.UUID) -> Track:
        # Пустую коллекцию задаём явно: иначе после commit обращение к ней
        # уйдёт в ленивую подгрузку вне greenlet-контекста и упадёт.
        track.courses = []
        mark_created(track, actor_id)
        self._tracks.add(track)
        await self._transaction.commit()
        return track

    async def update(
        self, track_id: uuid.UUID, changes: dict[str, Any], actor_id: uuid.UUID
    ) -> Track:
        track = await self._tracks.get(track_id)
        if track is None:
            raise NotFoundError("Трек не найден")
        apply_changes(track, changes, required={"title", "slug", "status"})
        mark_updated(track, actor_id)
        await self._transaction.commit()
        return track

    async def attach_course(
        self,
        track_id: uuid.UUID,
        course_id: uuid.UUID,
        actor_id: uuid.UUID,
    ) -> None:
        if await self._tracks.get_for_update(track_id) is None:
            raise NotFoundError("Трек не найден")
        if await self._courses.get(course_id) is None:
            raise NotFoundError("Курс не найден")
        link = await self._tracks.get_course_link(track_id, course_id)
        if link is not None:
            return
        links = await self._tracks.list_course_links(track_id)
        position = max((item.position for item in links), default=-1) + 1
        self._tracks.add_course_link(
            TrackCourse(
                track_id=track_id,
                course_id=course_id,
                position=position,
                created_by=actor_id,
                updated_by=actor_id,
            ),
        )
        await self._transaction.commit()

    async def reorder_courses(
        self,
        track_id: uuid.UUID,
        course_ids: Sequence[uuid.UUID],
        actor_id: uuid.UUID,
    ) -> None:
        if await self._tracks.get_for_update(track_id) is None:
            raise NotFoundError("Трек не найден")
        links = await self._tracks.list_course_links(track_id)
        apply_order_by(
            links,
            course_ids,
            actor_id,
            subject="курсы трека",
            key=lambda link: link.course_id,
        )
        await self._transaction.commit()

    async def detach_course(self, track_id: uuid.UUID, course_id: uuid.UUID) -> None:
        if await self._tracks.get_for_update(track_id) is None:
            raise NotFoundError("Трек не найден")
        link = await self._tracks.get_course_link(track_id, course_id)
        if link is None:
            raise NotFoundError("Курс не входит в трек")
        await self._tracks.delete_course_link(link)
        await self._transaction.commit()

    async def delete(self, track_id: uuid.UUID) -> None:
        track = await self._tracks.get(track_id)
        if track is None:
            raise NotFoundError("Трек не найден")
        await self._tracks.delete(track)
        await self._transaction.commit()
