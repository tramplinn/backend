import uuid_utils.compat as uuid
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from tramplin.core.time import utc_now
from tramplin.infrastructure.repositories.base import Repository
from tramplin.models.base import soft_delete
from tramplin.models.content import Course, Lesson, Module, ModuleItem
from tramplin.models.enums import ContentStatus
from tramplin.models.quizzes import Quiz, QuizQuestion


class CourseRepository(Repository):
    async def list(self, *, published_only: bool) -> list[Course]:
        stmt = (
            select(Course)
            .options(selectinload(Course.cover_asset), selectinload(Course.tags))
            .order_by(Course.title)
        )
        if published_only:
            stmt = stmt.where(Course.status == ContentStatus.PUBLISHED)
        return list(await self._session.scalars(stmt))

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
        # Каскад вручную: ORM cascade="delete-orphan" не срабатывает на выставление
        # флага, а модули/уроки/тесты курса не должны остаться "живыми" сиротами.
        soft_delete(course)
        now = utc_now()
        module_ids = select(Module.id).where(Module.course_id == course.id)
        await self._session.execute(
            update(Module)
            .where(Module.course_id == course.id)
            .values(is_deleted=True, deleted_at=now)
        )
        await self._session.execute(
            update(Lesson)
            .where(Lesson.module_id.in_(module_ids))
            .values(is_deleted=True, deleted_at=now)
        )
        await self._session.execute(
            update(Quiz)
            .where(Quiz.module_id.in_(module_ids))
            .values(is_deleted=True, deleted_at=now)
        )
