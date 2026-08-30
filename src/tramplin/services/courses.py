from typing import Any, Protocol

import uuid_utils.compat as uuid

from tramplin.core.errors import InvalidUpdateError, NotFoundError
from tramplin.models.assets import Asset
from tramplin.models.content import Course
from tramplin.models.enums import AssetMime
from tramplin.services.assets import AssetRepositoryPort
from tramplin.services.contracts import Transaction
from tramplin.services.entity_updates import apply_changes, mark_created, mark_updated


class CourseRepositoryPort(Protocol):
    async def list(self, *, published_only: bool) -> list[Course]: ...

    async def get(self, course_id: uuid.UUID) -> Course | None: ...

    async def get_by_slug(self, slug: str, *, published_only: bool) -> Course | None: ...

    def add(self, course: Course) -> Course: ...

    async def delete(self, course: Course) -> None: ...


class CourseService:
    def __init__(
        self,
        transaction: Transaction,
        courses: CourseRepositoryPort,
        assets: AssetRepositoryPort,
    ) -> None:
        self._transaction = transaction
        self._courses = courses
        self._assets = assets

    async def list(self, *, published_only: bool = True) -> list[Course]:
        return await self._courses.list(published_only=published_only)

    async def get(self, slug: str, *, published_only: bool = True) -> Course:
        course = await self._courses.get_by_slug(slug, published_only=published_only)
        if course is None:
            raise NotFoundError("Курс не найден")
        return course

    async def create(self, course: Course, actor_id: uuid.UUID) -> Course:
        course.cover_asset = await self._resolve_cover(course.cover_asset_id)
        mark_created(course, actor_id)
        self._courses.add(course)
        await self._transaction.commit()
        return course

    async def update(
        self, course_id: uuid.UUID, changes: dict[str, Any], actor_id: uuid.UUID
    ) -> Course:
        course = await self._courses.get(course_id)
        if course is None:
            raise NotFoundError("Курс не найден")
        if "cover_asset_id" in changes:
            cover_asset_id = changes.pop("cover_asset_id")
            course.cover_asset = await self._resolve_cover(cover_asset_id)
            course.cover_asset_id = cover_asset_id
        apply_changes(course, changes, required={"title", "slug", "status"})
        mark_updated(course, actor_id)
        await self._transaction.commit()
        return course

    async def delete(self, course_id: uuid.UUID) -> None:
        course = await self._courses.get(course_id)
        if course is None:
            raise NotFoundError("Курс не найден")
        await self._courses.delete(course)
        await self._transaction.commit()

    async def _resolve_cover(self, asset_id: uuid.UUID | None) -> Asset | None:
        if asset_id is None:
            return None
        asset = await self._assets.get(asset_id)
        if asset is None:
            raise NotFoundError("Файл обложки не найден")
        if asset.mime is AssetMime.PDF:
            raise InvalidUpdateError("Обложкой курса может быть только изображение")
        return asset
