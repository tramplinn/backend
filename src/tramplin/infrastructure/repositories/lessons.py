import uuid_utils.compat as uuid
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from tramplin.infrastructure.repositories.base import Repository
from tramplin.models.base import soft_delete
from tramplin.models.content import Course, InterviewCard, Lesson, Module
from tramplin.models.enums import ContentStatus


class LessonRepository(Repository):
    async def get(self, lesson_id: uuid.UUID, *, published_only: bool) -> Lesson | None:
        stmt = (
            select(Lesson)
            .join(Module, Lesson.module_id == Module.id)
            .join(Course, Module.course_id == Course.id)
            .where(Lesson.id == lesson_id)
        )
        if published_only:
            stmt = stmt.where(
                Lesson.status == ContentStatus.PUBLISHED,
                Module.status == ContentStatus.PUBLISHED,
                Course.status == ContentStatus.PUBLISHED,
            )
        return (await self._session.scalars(stmt)).one_or_none()

    async def get_with_interview_cards(self, lesson_id: uuid.UUID) -> Lesson | None:
        stmt = (
            select(Lesson)
            .where(Lesson.id == lesson_id)
            .options(selectinload(Lesson.interview_cards))
        )
        return (await self._session.scalars(stmt)).one_or_none()

    def add(self, lesson: Lesson) -> Lesson:
        self._session.add(lesson)
        return lesson

    async def delete(self, lesson: Lesson) -> None:
        soft_delete(lesson)

    async def list_interview_cards(self, lesson_id: uuid.UUID) -> list[InterviewCard]:
        stmt = (
            select(InterviewCard)
            .where(InterviewCard.lesson_id == lesson_id)
            .order_by(InterviewCard.position)
        )
        return list(await self._session.scalars(stmt))
