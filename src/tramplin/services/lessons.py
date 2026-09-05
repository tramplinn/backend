from typing import Any, Protocol

import uuid_utils.compat as uuid
from anyio import to_thread

from tramplin.core.errors import NotFoundError
from tramplin.models.content import InterviewCard, Lesson
from tramplin.services.contracts import Transaction
from tramplin.services.entity_updates import (
    mark_created,
    mark_updated,
    require,
    validate_required_updates,
)
from tramplin.services.lesson_markdown import RenderedLessonContent, render_lesson_content
from tramplin.services.modules import ModuleRepositoryPort, next_module_item


class LessonRepositoryPort(Protocol):
    async def get(self, lesson_id: uuid.UUID, *, published_only: bool) -> Lesson | None: ...

    async def get_with_interview_cards(self, lesson_id: uuid.UUID) -> Lesson | None: ...

    def add(self, lesson: Lesson) -> Lesson: ...

    async def delete(self, lesson: Lesson) -> None: ...

    async def list_interview_cards(self, lesson_id: uuid.UUID) -> list[InterviewCard]: ...


class LessonService:
    def __init__(
        self,
        transaction: Transaction,
        lessons: LessonRepositoryPort,
        modules: ModuleRepositoryPort,
    ) -> None:
        self._transaction = transaction
        self._lessons = lessons
        self._modules = modules

    async def get(self, lesson_id: uuid.UUID, *, published_only: bool = True) -> Lesson:
        return require(
            await self._lessons.get(lesson_id, published_only=published_only),
            NotFoundError("Урок не найден"),
        )

    async def list_interview_cards(
        self,
        lesson_id: uuid.UUID,
        *,
        published_only: bool = True,
    ) -> list[InterviewCard]:
        await self.get(lesson_id, published_only=published_only)
        return await self._lessons.list_interview_cards(lesson_id)

    async def create(self, module_id: uuid.UUID, lesson: Lesson, actor_id: uuid.UUID) -> Lesson:
        require(await self._modules.get_for_update(module_id), NotFoundError("Модуль не найден"))
        lesson.module_id = module_id
        mark_created(lesson, actor_id)
        self._apply_rendered_content(lesson, await self.preview(lesson.body_md), actor_id)
        self._lessons.add(lesson)
        # ModuleItem.lesson — viewonly, ORM не строит по нему порядок flush: без явного
        # flush тут INSERT INTO module_items мог уйти раньше INSERT INTO lessons и
        # упасть на fk_module_items_lesson_id_module_id_lessons.
        await self._transaction.flush()
        await self._append_to_module(module_id, actor_id, lesson_id=lesson.id)
        await self._transaction.commit()
        return lesson

    async def update(
        self, lesson_id: uuid.UUID, changes: dict[str, Any], actor_id: uuid.UUID
    ) -> Lesson:
        lesson = require(
            await self._lessons.get_with_interview_cards(lesson_id),
            NotFoundError("Урок не найден"),
        )
        body_md = changes.get("body_md")
        validate_required_updates(changes, {"title", "slug", "body_md", "status"})
        lesson.title = changes.get("title", lesson.title)
        lesson.slug = changes.get("slug", lesson.slug)
        lesson.est_minutes = changes.get("est_minutes", lesson.est_minutes)
        lesson.body_md = changes.get("body_md", lesson.body_md)
        lesson.status = changes.get("status", lesson.status)
        if body_md is not None:
            self._apply_rendered_content(lesson, await self.preview(body_md), actor_id)
        mark_updated(lesson, actor_id)
        await self._transaction.commit()
        return lesson

    async def _append_to_module(
        self,
        module_id: uuid.UUID,
        actor_id: uuid.UUID,
        *,
        lesson_id: uuid.UUID,
    ) -> None:
        items = await self._modules.list_items(module_id)
        self._modules.add_item(
            next_module_item(
                items,
                module_id=module_id,
                actor_id=actor_id,
                lesson_id=lesson_id,
            )
        )

    async def delete(self, lesson_id: uuid.UUID) -> None:
        lesson = await self.get(lesson_id, published_only=False)
        await self._lessons.delete(lesson)
        await self._transaction.commit()

    async def preview(self, body_md: str) -> RenderedLessonContent:
        return await to_thread.run_sync(render_lesson_content, body_md)

    @staticmethod
    def _apply_rendered_content(
        lesson: Lesson,
        rendered: RenderedLessonContent,
        actor_id: uuid.UUID,
    ) -> None:
        lesson.body_html = rendered.body_html
        lesson.interview_cards = [
            InterviewCard(
                lesson_id=lesson.id,
                position=card.position,
                question_md=card.question_md,
                answer_md=card.answer_md,
                created_by=actor_id,
                updated_by=actor_id,
            )
            for card in rendered.interview_cards
        ]
