import uuid_utils.compat as uuid
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from tramplin.infrastructure.repositories.base import Repository
from tramplin.models.content import Course, Module, ModuleItem
from tramplin.models.enums import ContentStatus
from tramplin.models.quizzes import Quiz, QuizQuestion


class CourseRepository(Repository):
    async def list(self, *, published_only: bool) -> list[Course]:
        stmt = select(Course).options(selectinload(Course.cover_asset)).order_by(Course.title)
        if published_only:
            stmt = stmt.where(Course.status == ContentStatus.PUBLISHED)
        return list(await self._session.scalars(stmt))

    async def get(self, course_id: uuid.UUID) -> Course | None:
        stmt = (
            select(Course).where(Course.id == course_id).options(selectinload(Course.cover_asset))
        )
        return (await self._session.scalars(stmt)).one_or_none()

    async def get_by_slug(self, slug: str, *, published_only: bool) -> Course | None:
        stmt = (
            select(Course)
            .where(Course.slug == slug)
            .options(
                selectinload(Course.cover_asset),
                selectinload(Course.modules)
                .selectinload(Module.items)
                .selectinload(ModuleItem.lesson),
                selectinload(Course.modules)
                .selectinload(Module.items)
                .selectinload(ModuleItem.quiz)
                .selectinload(Quiz.questions),
                selectinload(Course.modules)
                .selectinload(Module.items)
                .selectinload(ModuleItem.quiz)
                .selectinload(Quiz.questions)
                .selectinload(QuizQuestion.attachments),
            )
        )
        if published_only:
            stmt = stmt.where(Course.status == ContentStatus.PUBLISHED)
        return (await self._session.scalars(stmt)).one_or_none()

    def add(self, course: Course) -> Course:
        self._session.add(course)
        return course

    async def delete(self, course: Course) -> None:
        await self._session.delete(course)
