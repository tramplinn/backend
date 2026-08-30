import uuid_utils.compat as uuid
from sqlalchemy import delete, select

from tramplin.infrastructure.repositories.base import Repository
from tramplin.models.content import Lesson, Module
from tramplin.models.progress import LessonProgress


class LessonProgressRepository(Repository):
    async def get(
        self,
        user_id: uuid.UUID,
        lesson_id: uuid.UUID,
    ) -> LessonProgress | None:
        return await self._session.get(LessonProgress, (user_id, lesson_id))

    async def list(
        self,
        user_id: uuid.UUID,
        *,
        course_id: uuid.UUID | None = None,
    ) -> list[LessonProgress]:
        stmt = select(LessonProgress).where(LessonProgress.user_id == user_id)
        if course_id is not None:
            stmt = (
                stmt.join(Lesson, LessonProgress.lesson_id == Lesson.id)
                .join(Module, Lesson.module_id == Module.id)
                .where(Module.course_id == course_id)
            )
        stmt = stmt.order_by(LessonProgress.completed_at)
        return list(await self._session.scalars(stmt))

    def add(self, progress: LessonProgress) -> LessonProgress:
        self._session.add(progress)
        return progress

    async def delete(self, user_id: uuid.UUID, lesson_id: uuid.UUID) -> None:
        stmt = delete(LessonProgress).where(
            LessonProgress.user_id == user_id,
            LessonProgress.lesson_id == lesson_id,
        )
        await self._session.execute(stmt)
