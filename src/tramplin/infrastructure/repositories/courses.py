import uuid_utils.compat as uuid
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from tramplin.infrastructure.repositories.base import Repository
from tramplin.models.content import Course, Module, ModuleItem
from tramplin.models.enums import ContentStatus
from tramplin.models.quizzes import Quiz, QuizQuestion


class CourseRepository(Repository):
    async def list(
        self,
        *,
        published_only: bool,
        limit: int,
        offset: int,
    ) -> tuple[list[Course], int]:
        stmt = (
            select(Course)
            .options(selectinload(Course.cover_asset), selectinload(Course.tags))
            .order_by(Course.title)
        )
        count_stmt = select(func.count()).select_from(Course)
        if published_only:
            stmt = stmt.where(Course.status == ContentStatus.PUBLISHED)
            count_stmt = count_stmt.where(Course.status == ContentStatus.PUBLISHED)
        total = await self._session.scalar(count_stmt)
        items = await self._session.scalars(stmt.limit(limit).offset(offset))
        return list(items), total or 0

    async def get(self, course_id: uuid.UUID) -> Course | None:
        stmt = (
            select(Course)
            .where(Course.id == course_id)
            .options(selectinload(Course.cover_asset), selectinload(Course.tags))
        )
        return (await self._session.scalars(stmt)).one_or_none()

    async def get_by_slug(self, slug: str, *, published_only: bool) -> Course | None:
        stmt = (
            select(Course)
            .where(Course.slug == slug)
            .options(
                selectinload(Course.cover_asset),
                selectinload(Course.tags),
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
                selectinload(Course.modules)
                .selectinload(Module.items)
                .selectinload(ModuleItem.practice_set),
            )
        )
        if published_only:
            stmt = stmt.where(Course.status == ContentStatus.PUBLISHED)
        return (await self._session.scalars(stmt)).one_or_none()

    async def delete_cascade(self, course: Course) -> None:
        # Модули, уроки, тесты и связи трека каскадно удаляются на уровне БД
        # (FK ondelete="CASCADE"), отдельного обхода дерева не требуется.
        await self.delete(course)
