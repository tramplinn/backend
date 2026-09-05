import math
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

import uuid_utils.compat as uuid

from tramplin.core.config import Settings
from tramplin.core.time import utc_now
from tramplin.infrastructure.llm import LlmClient
from tramplin.models.algorithms import AlgorithmProblem
from tramplin.models.content import Course
from tramplin.models.enums import RecommendationEntityType
from tramplin.models.users import User
from tramplin.services.contracts import EmbeddingQueue, Transaction
from tramplin.services.recommendation_ports import (
    EmbeddingDispatchRepositoryPort,
    EmbeddingWorkerRepositoryPort,
    RecommendationRepositoryPort,
)

_WEIGHT_EMBED = 0.5
_WEIGHT_OVERLAP = 0.35
_WEIGHT_NOVELTY = 0.15
_THRESHOLD = 0.15
_NOVELTY_WINDOW_DAYS = 30
_TOP_N = 5
_STATEMENT_CHARS = 4000


class _HasTag(Protocol):
    name: str


class _HasSignal(Protocol):
    @property
    def tags(self) -> Sequence[_HasTag]: ...

    embedding: list[float] | None
    created_at: datetime


def _tag_names(item: _HasSignal) -> list[str]:
    return [tag.name for tag in item.tags]


@dataclass(frozen=True, slots=True)
class Recommendations:
    courses: list[Course]
    algorithms: list[AlgorithmProblem]


def _topic_counts(items: Sequence[_HasSignal]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for item in items:
        counts.update(_tag_names(item))
    return counts


def _average_embedding(items: Sequence[_HasSignal]) -> list[float] | None:
    vectors = [item.embedding for item in items if item.embedding is not None]
    if not vectors:
        return None
    dim = len(vectors[0])
    return [sum(vector[i] for vector in vectors) / len(vectors) for i in range(dim)]


def _cosine(a: list[float] | None, b: list[float] | None) -> float | None:
    if a is None or b is None:
        return None
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return None
    return dot / (norm_a * norm_b)


def _jaccard(a: Iterable[str], b: Iterable[str]) -> float:
    set_a, set_b = set(a), set(b)
    union = set_a | set_b
    if not union:
        return 0.0
    return len(set_a & set_b) / len(union)


def _novelty(created_at: datetime) -> float:
    days = (utc_now() - created_at).total_seconds() / 86400
    return max(0.0, min(1.0, 1.0 - days / _NOVELTY_WINDOW_DAYS))


def _score(
    item: _HasSignal, user_topics: Counter[str], user_embedding: list[float] | None
) -> float:
    """Перенормировка: нет эмбеддинга у кандидата/профиля — его вес уходит в overlap,
    иначе отсутствие ещё не посчитанного эмбеддинга искусственно занижало бы скор."""
    overlap = _jaccard(user_topics.keys(), _tag_names(item))
    novelty = _novelty(item.created_at)
    cosine = _cosine(user_embedding, item.embedding)
    if cosine is None:
        return (_WEIGHT_EMBED + _WEIGHT_OVERLAP) * overlap + _WEIGHT_NOVELTY * novelty
    return _WEIGHT_EMBED * cosine + _WEIGHT_OVERLAP * overlap + _WEIGHT_NOVELTY * novelty


def _rank[T: _HasSignal](
    items: Sequence[T],
    user_topics: Counter[str],
    user_embedding: list[float] | None,
    *,
    cold_start: bool,
) -> list[T]:
    if cold_start:
        ordered = sorted(items, key=lambda item: _novelty(item.created_at), reverse=True)
        return ordered[:_TOP_N]
    scored = [(item, _score(item, user_topics, user_embedding)) for item in items]
    scored = [pair for pair in scored if pair[1] >= _THRESHOLD]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return [item for item, _ in scored[:_TOP_N]]


class RecommendationService:
    def __init__(
        self,
        session: Transaction,
        repo: RecommendationRepositoryPort,
        settings: Settings,
    ) -> None:
        self._session = session
        self._repo = repo
        self._settings = settings

    async def list_for(self, user: User | None) -> Recommendations:
        if user is None:
            return Recommendations(courses=[], algorithms=[])

        engaged_algorithms = await self._repo.engaged_algorithm_signal(user.id)
        engaged_courses = await self._repo.engaged_course_signal(user.id)
        candidate_algorithms = await self._repo.candidate_algorithm_problems(user.id)
        candidate_courses = await self._repo.candidate_courses(user.id)

        user_topics = _topic_counts([*engaged_algorithms, *engaged_courses])
        user_embedding = _average_embedding([*engaged_algorithms, *engaged_courses])
        cold_start = not user_topics and user_embedding is None

        if self._settings.embeddings_enabled:
            missing = [
                (RecommendationEntityType.ALGORITHM_PROBLEM, item.id)
                for item in (*engaged_algorithms, *candidate_algorithms)
                if item.embedding is None
            ] + [
                (RecommendationEntityType.COURSE, item.id)
                for item in (*engaged_courses, *candidate_courses)
                if item.embedding is None
            ]
            if missing:
                await self._repo.enqueue_embedding_jobs(missing)
                await self._session.commit()

        return Recommendations(
            courses=_rank(candidate_courses, user_topics, user_embedding, cold_start=cold_start),
            algorithms=_rank(
                candidate_algorithms, user_topics, user_embedding, cold_start=cold_start
            ),
        )


class EmbeddingDispatchService:
    def __init__(
        self,
        transaction: Transaction,
        repo: EmbeddingDispatchRepositoryPort,
        queue: EmbeddingQueue,
    ) -> None:
        self._transaction = transaction
        self._repo = repo
        self._queue = queue

    async def dispatch_next(self) -> bool:
        job = await self._repo.claim_embedding_job()
        if job is None:
            return False
        await self._queue.publish(job.entity_type, job.entity_id)
        job.dispatched_at = utc_now()
        job.attempts += 1
        job.last_error = None
        await self._transaction.commit()
        return True


def _algorithm_text(problem: AlgorithmProblem) -> str:
    parts = [problem.title, problem.statement_md[:_STATEMENT_CHARS]]
    if problem.tags:
        parts.append("темы: " + ", ".join(_tag_names(problem)))
    return "\n".join(parts)


def _course_text(course: Course) -> str:
    parts = [course.title, course.summary or ""]
    if course.tags:
        parts.append("темы: " + ", ".join(_tag_names(course)))
    return "\n".join(parts)


class EmbeddingWorkerService:
    def __init__(
        self,
        session: Transaction,
        repo: EmbeddingWorkerRepositoryPort,
        llm: LlmClient,
    ) -> None:
        self._session = session
        self._repo = repo
        self._llm = llm

    async def process(self, entity_type: RecommendationEntityType, entity_id: uuid.UUID) -> None:
        text = await self._build_text(entity_type, entity_id)
        if text is None:
            return
        [vector] = await self._llm.embed([text])
        await self._repo.set_embedding(entity_type, entity_id, vector)
        await self._session.commit()

    async def _build_text(
        self, entity_type: RecommendationEntityType, entity_id: uuid.UUID
    ) -> str | None:
        if entity_type is RecommendationEntityType.ALGORITHM_PROBLEM:
            problem = await self._repo.get_algorithm_problem(entity_id)
            return None if problem is None else _algorithm_text(problem)
        course = await self._repo.get_course(entity_id)
        return None if course is None else _course_text(course)
