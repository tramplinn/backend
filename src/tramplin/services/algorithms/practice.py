from datetime import timedelta

import uuid_utils.compat as uuid

from tramplin.core.config import Settings
from tramplin.core.errors import (
    InvalidAlgorithmProblemError,
    NotFoundError,
    RunnerBusyError,
    SessionExpiredError,
    TooManyRequestsError,
)
from tramplin.core.time import utc_now
from tramplin.models.algorithms import (
    AlgorithmJobOutbox,
    AlgorithmProblem,
    AlgorithmProgress,
    AlgorithmSubmission,
    PracticeSession,
    PracticeSet,
)
from tramplin.models.enums import (
    AlgorithmDifficulty,
    AlgorithmProgressStatus,
    AlgorithmProvider,
    PracticeMode,
    PracticeSessionStatus,
    SubmissionKind,
    SubmissionStatus,
)
from tramplin.services.algorithm_ports import AlgorithmPracticeRepositoryPort
from tramplin.services.algorithms.catalog import ProblemCatalog
from tramplin.services.contracts import Transaction
from tramplin.services.entity_updates import mark_created, mark_updated, require


class AlgorithmPracticeService:
    def __init__(
        self,
        transaction: Transaction,
        algorithms: AlgorithmPracticeRepositoryPort,
        settings: Settings,
    ) -> None:
        self._transaction = transaction
        self._algorithms = algorithms
        self._settings = settings

    async def get_set(self, set_id: uuid.UUID) -> PracticeSet:
        return require(
            await self._algorithms.get_set(set_id, published_only=True),
            NotFoundError("Набор практики не найден"),
        )

    async def list_catalog(
        self,
        user_id: uuid.UUID,
        *,
        difficulty: AlgorithmDifficulty | None = None,
        tag_id: uuid.UUID | None = None,
        query: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> ProblemCatalog:
        problems, total = await self._algorithms.list_published_problems(
            difficulty=difficulty, tag_id=tag_id, query=query, limit=limit, offset=offset
        )
        progress = await self._algorithms.progress_map(user_id, [item.id for item in problems])
        tags = await self._algorithms.published_tags()
        return ProblemCatalog(
            items=[(problem, progress.get(problem.id)) for problem in problems],
            tags=tags,
            total=total,
        )

    async def start_free_session(self, user_id: uuid.UUID) -> PracticeSession:
        """Сессия тренажёра вне набора: без дедлайна, любая опубликованная задача."""
        now = utc_now()
        practice_session = PracticeSession(
            practice_set_id=None,
            user_id=user_id,
            mode=PracticeMode.PRACTICE,
            status=PracticeSessionStatus.ACTIVE,
            started_at=now,
            deadline_at=None,
            completed_at=None,
            reflection_md=None,
        )
        mark_created(practice_session, user_id)
        self._algorithms.add_session(practice_session)
        await self._transaction.commit()
        return practice_session

    async def start_session(self, set_id: uuid.UUID, user_id: uuid.UUID) -> PracticeSession:
        practice_set = await self.get_set(set_id)
        now = utc_now()
        deadline = (
            now + timedelta(minutes=practice_set.duration_minutes)
            if practice_set.mode is PracticeMode.MOCK_INTERVIEW and practice_set.duration_minutes
            else None
        )
        practice_session = PracticeSession(
            practice_set_id=set_id,
            user_id=user_id,
            mode=practice_set.mode,
            status=PracticeSessionStatus.ACTIVE,
            started_at=now,
            deadline_at=deadline,
            completed_at=None,
            reflection_md=None,
        )
        mark_created(practice_session, user_id)
        self._algorithms.add_session(practice_session)
        await self._transaction.commit()
        return practice_session

    async def get_session(self, session_id: uuid.UUID, user_id: uuid.UUID) -> PracticeSession:
        session = await self._algorithms.get_session(session_id)
        if session is None or session.user_id != user_id:
            raise NotFoundError("Сессия практики не найдена")
        if (
            session.status is PracticeSessionStatus.ACTIVE
            and session.deadline_at
            and utc_now() >= session.deadline_at
        ):
            session.status = PracticeSessionStatus.EXPIRED
            session.completed_at = utc_now()
            await self._transaction.commit()
        return session

    async def complete_session(
        self, session_id: uuid.UUID, user_id: uuid.UUID, reflection_md: str | None
    ) -> PracticeSession:
        session = await self.get_session(session_id, user_id)
        if session.status is PracticeSessionStatus.ACTIVE:
            session.status = PracticeSessionStatus.COMPLETED
            session.completed_at = utc_now()
        session.reflection_md = reflection_md
        mark_updated(session, user_id)
        await self._transaction.commit()
        return session

    async def get_problem(self, problem_id: uuid.UUID) -> AlgorithmProblem:
        return require(
            await self._algorithms.get_problem(problem_id, published_only=True),
            NotFoundError("Алгоритмическая задача не найдена"),
        )

    async def enqueue(
        self,
        session_id: uuid.UUID,
        problem_id: uuid.UUID,
        user_id: uuid.UUID,
        kind: SubmissionKind,
        language: str,
        source_code: str,
        custom_input: str | None = None,
    ) -> AlgorithmSubmission:
        if len(source_code.encode()) > self._settings.algorithm_source_max_bytes:
            raise InvalidAlgorithmProblemError("Исходный код превышает допустимый размер")
        session = await self.get_session(session_id, user_id)
        if session.status is not PracticeSessionStatus.ACTIVE:
            raise SessionExpiredError()
        if (
            kind is SubmissionKind.SUBMIT
            and session.deadline_at
            and utc_now() >= session.deadline_at
        ):
            raise SessionExpiredError()
        practice_set = session.practice_set
        if practice_set is not None and problem_id not in {
            item.problem_id for item in practice_set.problems
        }:
            raise NotFoundError("Задача не входит в эту сессию")
        problem = await self.get_problem(problem_id)
        if problem.provider is not AlgorithmProvider.INTERNAL:
            raise InvalidAlgorithmProblemError("Внешняя задача решается на сайте провайдера")
        if language not in {template.language for template in problem.templates}:
            raise InvalidAlgorithmProblemError("Язык не разрешён для этой задачи")
        await self._algorithms.lock_user(user_id)
        if await self._algorithms.active_submissions(user_id):
            raise RunnerBusyError()
        now = utc_now()
        if (
            await self._algorithms.submission_count(user_id=user_id, since=now - timedelta(hours=1))
            >= self._settings.algorithm_runs_per_hour
        ):
            raise TooManyRequestsError("Превышен лимит запусков за час")
        if (
            await self._algorithms.submission_count(
                user_id=user_id, session_id=session_id, problem_id=problem_id
            )
            >= self._settings.algorithm_runs_per_session_problem
        ):
            raise TooManyRequestsError("Превышен лимит запусков задачи в этой сессии")
        submission = AlgorithmSubmission(
            session_id=session_id,
            problem_id=problem_id,
            user_id=user_id,
            kind=kind,
            language=language,
            source_code=source_code,
            custom_input=custom_input if kind is SubmissionKind.RUN else None,
            status=SubmissionStatus.QUEUED,
            verdict=None,
            runtime_ms=None,
            memory_kb=None,
            failed_test=None,
            stdout=None,
            stderr=None,
            safe_error=None,
            judge_token=None,
            result_json=None,
            claimed_at=None,
            finished_at=None,
            progress_counted=False,
        )
        mark_created(submission, user_id)
        self._algorithms.add_submission(submission)
        await self._transaction.flush()
        self._algorithms.add_outbox(
            AlgorithmJobOutbox(
                submission_id=submission.id,
                dispatched_at=None,
                attempts=0,
                last_error=None,
                created_by=user_id,
                updated_by=user_id,
            )
        )
        await self._transaction.commit()
        return submission

    async def get_submission(
        self, submission_id: uuid.UUID, user_id: uuid.UUID
    ) -> AlgorithmSubmission:
        submission = await self._algorithms.get_submission(submission_id)
        if submission is None or submission.user_id != user_id:
            raise NotFoundError("Запуск не найден")
        return submission

    async def get_progress(self, problem_id: uuid.UUID, user_id: uuid.UUID) -> AlgorithmProgress:
        await self.get_problem(problem_id)
        progress = await self._algorithms.get_progress(user_id, problem_id)
        return progress or new_progress(user_id, problem_id)

    async def list_solutions(
        self, problem_id: uuid.UUID, user_id: uuid.UUID
    ) -> list[AlgorithmSubmission]:
        await self.get_problem(problem_id)
        return await self._algorithms.list_accepted_submissions(user_id, problem_id, limit=50)

    async def update_reflection(
        self,
        problem_id: uuid.UUID,
        user_id: uuid.UUID,
        complexity_md: str | None,
        confidence: int | None,
        reflection_md: str | None,
    ) -> AlgorithmProgress:
        await self.get_problem(problem_id)
        progress = await self._algorithms.get_progress(user_id, problem_id)
        if progress is None:
            progress = new_progress(
                user_id,
                problem_id,
                confidence=confidence,
                complexity_md=complexity_md,
                reflection_md=reflection_md,
            )
            mark_created(progress, user_id)
            self._algorithms.add_progress(progress)
        else:
            progress.complexity_md, progress.confidence, progress.reflection_md = (
                complexity_md,
                confidence,
                reflection_md,
            )
            mark_updated(progress, user_id)
        await self._transaction.commit()
        return progress


def new_progress(
    user_id: uuid.UUID,
    problem_id: uuid.UUID,
    *,
    status: AlgorithmProgressStatus = AlgorithmProgressStatus.UNSEEN,
    confidence: int | None = None,
    complexity_md: str | None = None,
    reflection_md: str | None = None,
) -> AlgorithmProgress:
    return AlgorithmProgress(
        user_id=user_id,
        problem_id=problem_id,
        status=status,
        attempts=0,
        hints_used=0,
        first_solved_at=None,
        last_attempt_at=None,
        confidence=confidence,
        complexity_md=complexity_md,
        reflection_md=reflection_md,
        last_solution_language=None,
        last_solution_code=None,
        last_counted_submission_id=None,
    )
