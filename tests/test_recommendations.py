from datetime import timedelta
from typing import Any

import pytest
from pydantic import SecretStr

from tramplin.core.config import Settings
from tramplin.core.time import utc_now
from tramplin.models.algorithms import AlgorithmProblem
from tramplin.models.base import new_id
from tramplin.models.content import Course
from tramplin.models.enums import AlgorithmDifficulty, ContentStatus, RecommendationEntityType
from tramplin.models.recommendations import EmbeddingJobOutbox
from tramplin.models.tags import Tag
from tramplin.services import recommendations as module
from tramplin.services.recommendations import (
    EmbeddingDispatchService,
    EmbeddingWorkerService,
    RecommendationService,
)


def _problem(
    *, tags: list[str], embedding: list[float] | None = None, days_old: int = 0
) -> AlgorithmProblem:
    problem = AlgorithmProblem(
        provider="internal",
        external_key=None,
        external_url=None,
        title="Задача",
        statement_md="условие",
        statement_html="<p>условие</p>",
        difficulty=AlgorithmDifficulty.EASY,
        time_limit_ms=1000,
        memory_limit_kb=262144,
        status=ContentStatus.PUBLISHED,
    )
    problem.tags = [Tag(name=name) for name in tags]
    problem.embedding = embedding
    problem.created_at = utc_now() - timedelta(days=days_old)
    return problem


def _course(*, tags: list[str], embedding: list[float] | None = None, days_old: int = 0) -> Course:
    course = Course(
        title="Курс",
        summary="описание",
        slug="kurs",
        color=None,
        est_hours=5,
        status=ContentStatus.PUBLISHED,
    )
    course.tags = [Tag(name=name) for name in tags]
    course.embedding = embedding
    course.created_at = utc_now() - timedelta(days=days_old)
    return course


class TransactionFake:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1

    async def flush(self) -> None:
        pass


class SessionFake(TransactionFake):
    pass


class RecommendationsFake:
    def __init__(
        self,
        *,
        candidate_algorithms: list[AlgorithmProblem] | None = None,
        candidate_courses: list[Course] | None = None,
        engaged_algorithms: list[AlgorithmProblem] | None = None,
        engaged_courses: list[Course] | None = None,
    ) -> None:
        self._candidate_algorithms = candidate_algorithms or []
        self._candidate_courses = candidate_courses or []
        self._engaged_algorithms = engaged_algorithms or []
        self._engaged_courses = engaged_courses or []
        self.enqueued: list[tuple[RecommendationEntityType, Any]] = []
        self.jobs: dict[Any, EmbeddingJobOutbox] = {}
        self.problems: dict[Any, AlgorithmProblem] = {}
        self.courses: dict[Any, Course] = {}
        self.embeddings_set: list[tuple[RecommendationEntityType, Any, list[float]]] = []

    async def candidate_algorithm_problems(self, user_id: Any) -> list[AlgorithmProblem]:
        return self._candidate_algorithms

    async def candidate_courses(self, user_id: Any) -> list[Course]:
        return self._candidate_courses

    async def engaged_algorithm_signal(self, user_id: Any) -> list[AlgorithmProblem]:
        return self._engaged_algorithms

    async def engaged_course_signal(self, user_id: Any) -> list[Course]:
        return self._engaged_courses

    async def enqueue_embedding_jobs(
        self, items: list[tuple[RecommendationEntityType, Any]]
    ) -> None:
        self.enqueued.extend(items)

    async def claim_embedding_job(self) -> EmbeddingJobOutbox | None:
        return next((job for job in self.jobs.values() if job.dispatched_at is None), None)

    async def get_algorithm_problem(self, problem_id: Any) -> AlgorithmProblem | None:
        return self.problems.get(problem_id)

    async def get_course(self, course_id: Any) -> Course | None:
        return self.courses.get(course_id)

    async def set_embedding(
        self, entity_type: RecommendationEntityType, entity_id: Any, embedding: list[float]
    ) -> None:
        self.embeddings_set.append((entity_type, entity_id, embedding))


class QueueFake:
    def __init__(self) -> None:
        self.messages: list[tuple[RecommendationEntityType, Any]] = []

    async def publish(self, entity_type: RecommendationEntityType, entity_id: Any) -> None:
        self.messages.append((entity_type, entity_id))


class LlmFake:
    def __init__(self, vectors: list[list[float]]) -> None:
        self.vectors = vectors
        self.requested: list[str] = []

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.requested.extend(texts)
        return self.vectors


def _settings(**overrides: Any) -> Settings:
    base = Settings(
        _env_file=None,
        jwt_secret=SecretStr("test-secret-value-at-least-32-bytes"),
        github_client_id="cid",
        github_client_secret=SecretStr("csecret"),
    )
    return base.model_copy(update=overrides)


def test_cosine_similarity_of_identical_vectors_is_one() -> None:
    assert module._cosine([1.0, 0.0], [1.0, 0.0]) == 1.0
    assert module._cosine([1.0, 0.0], [0.0, 1.0]) == 0.0
    assert module._cosine(None, [1.0]) is None
    assert module._cosine([0.0, 0.0], [1.0, 1.0]) is None


def test_jaccard_overlap_of_topic_sets() -> None:
    assert module._jaccard(["a", "b"], ["b", "c"]) == 1 / 3
    assert module._jaccard([], []) == 0.0


def test_novelty_decays_linearly_and_clamps() -> None:
    assert module._novelty(utc_now()) == pytest.approx(1.0)
    assert module._novelty(utc_now() - timedelta(days=30)) == pytest.approx(0.0, abs=1e-6)
    assert module._novelty(utc_now() - timedelta(days=60)) == 0.0


def test_score_renormalizes_weight_when_embedding_missing() -> None:
    from collections import Counter

    item = _problem(tags=["a"])
    user_topics = Counter({"a": 1})
    # без эмбеддинга у профиля/кандидата — весь вес embed уходит в overlap
    score = module._score(item, user_topics, None)
    expected = (module._WEIGHT_EMBED + module._WEIGHT_OVERLAP) * 1.0 + module._WEIGHT_NOVELTY
    assert score == pytest.approx(expected, abs=1e-6)


async def test_list_for_returns_empty_for_guest() -> None:
    repo = RecommendationsFake()
    service = RecommendationService(SessionFake(), repo, _settings())
    result = await service.list_for(None)
    assert result.courses == []
    assert result.algorithms == []


async def test_list_for_ranks_candidates_above_threshold() -> None:
    from tramplin.models.users import User

    matching = _problem(tags=["графы"], days_old=1)
    unrelated = _problem(tags=["строки"], days_old=1000)
    repo = RecommendationsFake(
        candidate_algorithms=[matching, unrelated],
        engaged_algorithms=[_problem(tags=["графы"], days_old=5)],
    )
    session = SessionFake()
    service = RecommendationService(session, repo, _settings())
    user = User(login="u", role="student", is_active=True)

    result = await service.list_for(user)

    assert result.algorithms == [matching]


async def test_list_for_cold_start_ranks_by_novelty_without_threshold() -> None:
    from tramplin.models.users import User

    old = _problem(tags=[], days_old=1000)
    fresh = _problem(tags=[], days_old=0)
    repo = RecommendationsFake(candidate_algorithms=[old, fresh])
    service = RecommendationService(SessionFake(), repo, _settings())
    user = User(login="u", role="student", is_active=True)

    result = await service.list_for(user)

    assert result.algorithms == [fresh, old]


async def test_list_for_enqueues_missing_embeddings_only_when_enabled() -> None:
    from tramplin.models.users import User

    problem = _problem(tags=["графы"])
    repo = RecommendationsFake(candidate_algorithms=[problem])
    session = SessionFake()
    user = User(login="u", role="student", is_active=True)

    disabled = RecommendationService(session, repo, _settings())
    await disabled.list_for(user)
    assert repo.enqueued == []

    enabled = RecommendationService(
        session,
        repo,
        _settings(llm_api_key=SecretStr("key"), embedding_model="text-embedding-3-small"),
    )
    await enabled.list_for(user)
    assert (RecommendationEntityType.ALGORITHM_PROBLEM, problem.id) in repo.enqueued
    assert session.commits == 1


async def test_embedding_dispatch_service_dispatches_once() -> None:
    repo = RecommendationsFake()
    entity_id = new_id()
    job = EmbeddingJobOutbox(
        entity_type=RecommendationEntityType.ALGORITHM_PROBLEM,
        entity_id=entity_id,
        dispatched_at=None,
        attempts=0,
        last_error="old",
    )
    repo.jobs[job.id] = job
    tx = TransactionFake()
    queue = QueueFake()
    dispatch = EmbeddingDispatchService(tx, repo, queue)

    assert await dispatch.dispatch_next()
    assert queue.messages == [(RecommendationEntityType.ALGORITHM_PROBLEM, entity_id)]
    assert job.dispatched_at is not None
    assert job.attempts == 1
    assert job.last_error is None
    assert tx.commits == 1
    assert not await dispatch.dispatch_next()


async def test_embedding_worker_service_embeds_and_stores() -> None:
    problem = _problem(tags=["графы"])
    repo = RecommendationsFake()
    repo.problems[problem.id] = problem
    llm = LlmFake([[0.1, 0.2, 0.3]])
    session = SessionFake()
    worker = EmbeddingWorkerService(session, repo, llm)  # type: ignore[arg-type]

    await worker.process(RecommendationEntityType.ALGORITHM_PROBLEM, problem.id)

    assert repo.embeddings_set == [
        (RecommendationEntityType.ALGORITHM_PROBLEM, problem.id, [0.1, 0.2, 0.3])
    ]
    assert session.commits == 1
    assert llm.requested


async def test_embedding_worker_service_skips_missing_entity() -> None:
    repo = RecommendationsFake()
    llm = LlmFake([[0.1]])
    session = SessionFake()
    worker = EmbeddingWorkerService(session, repo, llm)  # type: ignore[arg-type]

    await worker.process(RecommendationEntityType.COURSE, new_id())

    assert repo.embeddings_set == []
    assert session.commits == 0
