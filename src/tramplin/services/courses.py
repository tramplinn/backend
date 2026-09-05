from typing import Any, Protocol

import uuid_utils.compat as uuid

from tramplin.core.errors import NotFoundError
from tramplin.models.content import Course
from tramplin.services.assets import AssetRepositoryPort, resolve_image_asset
from tramplin.services.contracts import Transaction
from tramplin.services.entity_updates import (
    mark_created,
    mark_updated,
    require,
    validate_required_updates,
)


class CourseRepositoryPort(Protocol):
    async def list(self, *, published_only: bool) -> list[Course]: ...

    async def get(self, course_id: uuid.UUID) -> Course | None: ...

    async def get_by_slug(self, slug: str, *, published_only: bool) -> Course | None: ...

    def add(self, course: Course) -> Course: ...

    async def delete_cascade(self, course: Course) -> None: ...


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
        return require(
            await self._courses.get_by_slug(slug, published_only=published_only),
            NotFoundError("Курс не найден"),
        )

    async def create(self, course: Course, actor_id: uuid.UUID) -> Course:
        course.cover_asset = await resolve_image_asset(
            self._assets, course.cover_asset_id, owner="курса"
        )
        mark_created(course, actor_id)
        self._courses.add(course)
        await self._transaction.commit()
        return course

    async def update(
        self, course_id: uuid.UUID, changes: dict[str, Any], actor_id: uuid.UUID
    ) -> Course:
        course = require(await self._courses.get(course_id), NotFoundError("Курс не найден"))
        if "cover_asset_id" in changes:
            cover_asset_id = changes.pop("cover_asset_id")
            course.cover_asset = await resolve_image_asset(
                self._assets, cover_asset_id, owner="курса"
            )
            course.cover_asset_id = cover_asset_id
        validate_required_updates(changes, {"title", "slug", "status"})
        course.title = changes.get("title", course.title)
        course.slug = changes.get("slug", course.slug)
        course.summary = changes.get("summary", course.summary)
        course.color = changes.get("color", course.color)
        course.est_hours = changes.get("est_hours", course.est_hours)
        course.status = changes.get("status", course.status)
        mark_updated(course, actor_id)
        await self._transaction.commit()
        return course

    async def delete(self, course_id: uuid.UUID) -> None:
        course = require(await self._courses.get(course_id), NotFoundError("Курс не найден"))
        await self._courses.delete_cascade(course)
        await self._transaction.commit()
