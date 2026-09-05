import uuid_utils.compat as uuid
from sqlalchemy import and_, distinct, func, or_, select
from sqlalchemy.orm import selectinload

from tramplin.infrastructure.repositories.base import Repository
from tramplin.models.algorithms import AlgorithmProgress
from tramplin.models.content import Course, Lesson, Module
from tramplin.models.enums import AlgorithmProgressStatus, ContentStatus, UserRole
from tramplin.models.progress import LessonProgress, QuizAttempt
from tramplin.models.users import User
from tramplin.services.contracts import CourseActivity, ProfileStats

type CourseActivities = list[CourseActivity]


class UserRepository(Repository):
    async def list(
        self,
        *,
        query: str | None,
        role: UserRole | None,
        is_active: bool | None,
        limit: int,
        offset: int,
    ) -> tuple[list[User], int]:
        filters = []
        if query:
            pattern = f"%{query}%"
            filters.append(
                or_(
                    User.login.ilike(pattern),
                    User.name.ilike(pattern),
                    User.email.ilike(pattern),
                    User.student_number.ilike(pattern),
                    User.specialty.ilike(pattern),
                )
            )
        if role is not None:
            filters.append(User.role == role)
        if is_active is not None:
            filters.append(User.is_active == is_active)

        count_stmt = select(func.count()).select_from(User).where(*filters)
        total = await self._session.scalar(count_stmt)
        stmt = select(User).where(*filters).order_by(User.login).limit(limit).offset(offset)
        return list(await self._session.scalars(stmt)), total or 0

    async def get(self, user_id: uuid.UUID) -> User | None:
        return await self._session.get(User, user_id)

    async def get_with_identities(self, user_id: uuid.UUID) -> User | None:
        stmt = select(User).where(User.id == user_id).options(selectinload(User.identities))
        return (await self._session.scalars(stmt)).one_or_none()

    async def get_active_by_login(self, login: str) -> User | None:
        stmt = select(User).where(User.login == login, User.is_active.is_(True))
        return (await self._session.scalars(stmt)).one_or_none()

    async def public_stats(self, user_id: uuid.UUID) -> ProfileStats:
        completed = await self._session.scalar(
            select(func.count())
            .select_from(LessonProgress)
            .where(LessonProgress.user_id == user_id)
        )
        passed = await self._session.scalar(
            select(func.count(distinct(QuizAttempt.quiz_id))).where(
                QuizAttempt.user_id == user_id,
                QuizAttempt.score == QuizAttempt.max_score,
            )
        )
        solved = await self._session.scalar(
            select(func.count())
            .select_from(AlgorithmProgress)
            .where(
                AlgorithmProgress.user_id == user_id,
                AlgorithmProgress.status.in_(
                    [AlgorithmProgressStatus.SOLVED, AlgorithmProgressStatus.REVIEW]
                ),
            )
        )
        return ProfileStats(completed or 0, passed or 0, solved or 0)

    async def active_courses(self, user_id: uuid.UUID) -> CourseActivities:
        completed = func.count(LessonProgress.lesson_id)
        total = func.count(Lesson.id)
        stmt = (
            select(Course.slug, Course.title, Course.color, completed, total)
            .join(Module, Module.course_id == Course.id)
            .join(Lesson, Lesson.module_id == Module.id)
            .outerjoin(
                LessonProgress,
                and_(LessonProgress.lesson_id == Lesson.id, LessonProgress.user_id == user_id),
            )
            .where(
                Course.status == ContentStatus.PUBLISHED,
                Module.status == ContentStatus.PUBLISHED,
                Lesson.status == ContentStatus.PUBLISHED,
            )
            .group_by(Course.id)
            .having(completed > 0)
            .order_by(completed.desc(), Course.title)
        )
        rows = (await self._session.execute(stmt)).all()
        return [
            CourseActivity(
                slug=row.slug,
                title=row.title,
                color=row.color,
                completed_lessons=row[3],
                total_lessons=row[4],
            )
            for row in rows
        ]

    async def login_exists(self, login: str) -> bool:
        stmt = select(User.id).where(User.login == login).limit(1)
        return (await self._session.scalars(stmt)).first() is not None
