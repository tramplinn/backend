import uuid_utils.compat as uuid
from sqlalchemy import or_, select, update
from sqlalchemy.dialects.postgresql import insert

from tramplin.infrastructure.repositories.base import Repository
from tramplin.models.algorithms import AlgorithmProblem, AlgorithmProgress
from tramplin.models.content import Course, Lesson, Module
from tramplin.models.enums import AlgorithmProgressStatus, ContentStatus, RecommendationEntityType
from tramplin.models.progress import LessonProgress
from tramplin.models.recommendations import EmbeddingJobOutbox

_DONE_ALGORITHM_STATUSES = (AlgorithmProgressStatus.SOLVED, AlgorithmProgressStatus.REVIEW)


class RecommendationRepository(Repository):
    async def candidate_algorithm_problems(self, user_id: uuid.UUID) -> list[AlgorithmProblem]:
        stmt = (
            select(AlgorithmProblem)
            .outerjoin(
                AlgorithmProgress,
                (AlgorithmProgress.problem_id == AlgorithmProblem.id)
                & (AlgorithmProgress.user_id == user_id),
            )
            .where(AlgorithmProblem.status == ContentStatus.PUBLISHED)
            .where(
                or_(
                    AlgorithmProgress.status.is_(None),
                    AlgorithmProgress.status.not_in(_DONE_ALGORITHM_STATUSES),
                )
            )
        )
        return list(await self._session.scalars(stmt))

    async def candidate_courses(self, user_id: uuid.UUID) -> list[Course]:
        started = (
            select(Module.course_id)
            .join(Lesson, Lesson.module_id == Module.id)
            .join(LessonProgress, LessonProgress.lesson_id == Lesson.id)
            .where(LessonProgress.user_id == user_id)
        )
        stmt = (
            select(Course)
            .where(Course.status == ContentStatus.PUBLISHED)
            .where(Course.id.not_in(started))
        )
        return list(await self._session.scalars(stmt))

    async def engaged_algorithm_signal(self, user_id: uuid.UUID) -> list[AlgorithmProblem]:
        stmt = (
            select(AlgorithmProblem)
            .join(AlgorithmProgress, AlgorithmProgress.problem_id == AlgorithmProblem.id)
            .where(AlgorithmProgress.user_id == user_id)
            .where(AlgorithmProgress.status == AlgorithmProgressStatus.SOLVED)
        )
        return list(await self._session.scalars(stmt))

    async def engaged_course_signal(self, user_id: uuid.UUID) -> list[Course]:
        stmt = (
            select(Course)
            .join(Module, Module.course_id == Course.id)
            .join(Lesson, Lesson.module_id == Module.id)
            .join(LessonProgress, LessonProgress.lesson_id == Lesson.id)
            .where(LessonProgress.user_id == user_id)
            .distinct()
        )
        return list(await self._session.scalars(stmt))

    async def enqueue_embedding_jobs(
        self, items: list[tuple[RecommendationEntityType, uuid.UUID]]
    ) -> None:
        if not items:
            return
        stmt = (
            insert(EmbeddingJobOutbox)
            .values(
                [
                    {"entity_type": entity_type, "entity_id": entity_id}
                    for entity_type, entity_id in items
                ]
            )
            .on_conflict_do_nothing(index_elements=["entity_type", "entity_id"])
        )
        await self._session.execute(stmt)

    async def claim_embedding_job(self) -> EmbeddingJobOutbox | None:
        stmt = (
            select(EmbeddingJobOutbox)
            .where(EmbeddingJobOutbox.dispatched_at.is_(None))
            .order_by(EmbeddingJobOutbox.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        return (await self._session.scalars(stmt)).one_or_none()

    async def get_algorithm_problem(self, problem_id: uuid.UUID) -> AlgorithmProblem | None:
        return await self._session.get(AlgorithmProblem, problem_id)

    async def get_course(self, course_id: uuid.UUID) -> Course | None:
        return await self._session.get(Course, course_id)

    async def set_embedding(
        self,
        entity_type: RecommendationEntityType,
        entity_id: uuid.UUID,
        embedding: list[float],
    ) -> None:
        model = (
            AlgorithmProblem
            if entity_type is RecommendationEntityType.ALGORITHM_PROBLEM
            else Course
        )
        await self._session.execute(
            update(model).where(model.id == entity_id).values(embedding=embedding)
        )
