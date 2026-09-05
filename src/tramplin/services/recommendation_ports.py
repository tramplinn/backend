from typing import Protocol

import uuid_utils.compat as uuid

from tramplin.models.algorithms import AlgorithmProblem
from tramplin.models.content import Course
from tramplin.models.enums import RecommendationEntityType
from tramplin.models.recommendations import EmbeddingJobOutbox


class EngagedSignal(Protocol):
    """Темы и (опционально) эмбеддинг одной вовлечённой сущности — для профиля интереса."""

    topics: list[str]
    embedding: list[float] | None


class RecommendationRepositoryPort(Protocol):
    async def candidate_algorithm_problems(self, user_id: uuid.UUID) -> list[AlgorithmProblem]: ...

    async def candidate_courses(self, user_id: uuid.UUID) -> list[Course]: ...

    async def engaged_algorithm_signal(self, user_id: uuid.UUID) -> list[AlgorithmProblem]: ...

    async def engaged_course_signal(self, user_id: uuid.UUID) -> list[Course]: ...

    async def enqueue_embedding_jobs(
        self, items: list[tuple[RecommendationEntityType, uuid.UUID]]
    ) -> None: ...


class EmbeddingDispatchRepositoryPort(Protocol):
    async def claim_embedding_job(self) -> EmbeddingJobOutbox | None: ...


class EmbeddingWorkerRepositoryPort(Protocol):
    async def get_algorithm_problem(self, problem_id: uuid.UUID) -> AlgorithmProblem | None: ...

    async def get_course(self, course_id: uuid.UUID) -> Course | None: ...

    async def set_embedding(
        self,
        entity_type: RecommendationEntityType,
        entity_id: uuid.UUID,
        embedding: list[float],
    ) -> None: ...
