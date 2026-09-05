from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import uuid_utils.compat as uuid

from tramplin.core.config import Settings
from tramplin.core.errors import (
    ConflictError,
    InvalidAlgorithmProblemError,
    NotFoundError,
    RunnerBusyError,
    RunnerUnavailableError,
    SessionExpiredError,
    TooManyRequestsError,
)
from tramplin.core.time import utc_now
from tramplin.models.algorithms import (
    AlgorithmJobOutbox,
    AlgorithmProblem,
    AlgorithmProgress,
    AlgorithmSubmission,
    AlgorithmTemplate,
    AlgorithmTestCase,
    PracticeSession,
    PracticeSet,
    PracticeSetProblem,
)
from tramplin.models.enums import (
    AlgorithmDifficulty,
    AlgorithmProgressStatus,
    AlgorithmProvider,
    AlgorithmVerdict,
    ContentStatus,
    PracticeMode,
    PracticeSessionStatus,
    SubmissionKind,
    SubmissionStatus,
)
from tramplin.services.algorithm_execution import (
    CaseResult,
    bounded_output,
    execute_and_wait,
    wait_for_result,
)
from tramplin.services.algorithm_ports import (
    AlgorithmAuthoringRepositoryPort,
    AlgorithmDispatchRepositoryPort,
    AlgorithmModuleRepositoryPort,
    AlgorithmOperationsRepositoryPort,
    AlgorithmPracticeRepositoryPort,
    AlgorithmWorkerRepositoryPort,
)
from tramplin.services.contracts import (
    CodeRunner,
    RunnerLanguage,
    RunRequest,
    SubmissionQueue,
    Transaction,
)
from tramplin.services.entity_updates import (
    apply_order_by,
    mark_created,
    mark_updated,
    require,
    validate_required_updates,
)
from tramplin.services.lesson_markdown import render_markdown
from tramplin.services.modules import next_module_item


class AlgorithmAuthoringService:
    def __init__(
        self,
        transaction: Transaction,
        algorithms: AlgorithmAuthoringRepositoryPort,
        modules: AlgorithmModuleRepositoryPort,
        runner: CodeRunner,
        settings: Settings,
    ) -> None:
        self._transaction = transaction
        self._algorithms = algorithms
        self._modules = modules
        self._runner = runner
        self._settings = settings

    async def get_problem(self, problem_id: uuid.UUID) -> AlgorithmProblem:
        return require(
            await self._algorithms.get_problem(problem_id, published_only=False),
            NotFoundError("Алгоритмическая задача не найдена"),
        )

    async def list_problems(self) -> list[AlgorithmProblem]:
        return await self._algorithms.list_problems()

    async def create_problem(
        self, problem: AlgorithmProblem, actor_id: uuid.UUID
    ) -> AlgorithmProblem:
        publishing = problem.status is ContentStatus.PUBLISHED
        _validate_problem_source(problem, require_statement=publishing)
        problem.statement_html = render_markdown(problem.statement_md)
        problem.test_cases, problem.templates = [], []
        mark_created(problem, actor_id)
        self._algorithms.add_problem(problem)
        await self._transaction.commit()
        return problem

    async def update_problem(
        self, problem_id: uuid.UUID, changes: dict[str, Any], actor_id: uuid.UUID
    ) -> AlgorithmProblem:
        problem = await self.get_problem(problem_id)
        if (
            problem.status is ContentStatus.PUBLISHED
            and changes.get("status") is not ContentStatus.DRAFT
        ):
            raise ConflictError("Сначала верните задачу в черновик")
        if "statement_md" in changes:
            changes["statement_html"] = render_markdown(changes["statement_md"])
        validate_required_updates(changes, {"title", "difficulty", "status"})
        problem.provider = changes.get("provider", problem.provider)
        problem.external_key = changes.get("external_key", problem.external_key)
        problem.external_url = changes.get("external_url", problem.external_url)
        problem.title = changes.get("title", problem.title)
        problem.statement_md = changes.get("statement_md", problem.statement_md)
        problem.statement_html = changes.get("statement_html", problem.statement_html)
        problem.difficulty = changes.get("difficulty", problem.difficulty)
        problem.topics = changes.get("topics", problem.topics)
        problem.time_limit_ms = changes.get("time_limit_ms", problem.time_limit_ms)
        problem.memory_limit_kb = changes.get("memory_limit_kb", problem.memory_limit_kb)
        problem.status = changes.get("status", problem.status)
        publishing = problem.status is ContentStatus.PUBLISHED
        _validate_problem_source(problem, require_statement=publishing)
        if publishing:
            _ensure_publishable(problem)
        mark_updated(problem, actor_id)
        await self._transaction.commit()
        return problem

    async def delete_problem(self, problem_id: uuid.UUID) -> None:
        await self._algorithms.delete_problem(await self.get_problem(problem_id))
        await self._transaction.commit()

    async def add_case(
        self, problem_id: uuid.UUID, case: AlgorithmTestCase, actor_id: uuid.UUID
    ) -> AlgorithmTestCase:
        problem = await self.get_problem(problem_id)
        if problem.status is ContentStatus.PUBLISHED:
            raise ConflictError("Сначала верните задачу в черновик")
        case.problem_id = problem_id
        mark_created(case, actor_id)
        self._algorithms.add_test_case(case)
        problem.test_cases.append(case)
        _invalidate_templates(problem)
        await self._transaction.commit()
        return case

    async def update_case(
        self, case_id: uuid.UUID, changes: dict[str, Any], actor_id: uuid.UUID
    ) -> AlgorithmTestCase:
        case = require(
            await self._algorithms.get_test_case(case_id),
            NotFoundError("Тестовый пример не найден"),
        )
        problem = await self.get_problem(case.problem_id)
        if problem.status is ContentStatus.PUBLISHED:
            raise ConflictError("Сначала верните задачу в черновик")
        validate_required_updates(
            changes,
            {"position", "input", "expected_output", "is_sample", "weight"},
        )
        case.position = changes.get("position", case.position)
        case.input = changes.get("input", case.input)
        case.expected_output = changes.get("expected_output", case.expected_output)
        case.is_sample = changes.get("is_sample", case.is_sample)
        case.weight = changes.get("weight", case.weight)
        mark_updated(case, actor_id)
        _invalidate_templates(problem)
        await self._transaction.commit()
        return case

    async def delete_case(self, case_id: uuid.UUID) -> None:
        case = require(
            await self._algorithms.get_test_case(case_id),
            NotFoundError("Тестовый пример не найден"),
        )
        problem = await self.get_problem(case.problem_id)
        if problem.status is ContentStatus.PUBLISHED:
            raise ConflictError("Сначала верните задачу в черновик")
        await self._algorithms.delete_test_case(case)
        _invalidate_templates(problem)
        await self._transaction.commit()

    async def put_template(
        self,
        problem_id: uuid.UUID,
        language: str,
        starter_code: str,
        solution_code: str,
        actor_id: uuid.UUID,
    ) -> AlgorithmTemplate:
        problem = await self.get_problem(problem_id)
        if problem.status is ContentStatus.PUBLISHED:
            raise ConflictError("Сначала верните задачу в черновик")
        template = await self._algorithms.get_template(problem_id, language)
        if template is None:
            template = AlgorithmTemplate(
                problem_id=problem_id,
                language=language,
                starter_code=starter_code,
                solution_code=solution_code,
            )
            mark_created(template, actor_id)
            self._algorithms.add_template(template)
            problem.templates.append(template)
        else:
            template.starter_code, template.solution_code = starter_code, solution_code
            template.validated_at = None
            mark_updated(template, actor_id)
        await self._transaction.commit()
        return template

    async def validate_template(
        self, problem_id: uuid.UUID, language: str, actor_id: uuid.UUID
    ) -> AlgorithmTemplate:
        problem = await self.get_problem(problem_id)
        template = await self._algorithms.get_template(problem_id, language)
        if template is None or not template.solution_code.strip():
            raise InvalidAlgorithmProblemError("Добавьте эталонное решение")
        if not problem.test_cases:
            raise InvalidAlgorithmProblemError("Добавьте тестовые примеры")
        for case in problem.test_cases:
            result = await execute_and_wait(
                self._runner,
                RunRequest(
                    language,
                    template.solution_code,
                    case.input,
                    case.expected_output,
                    problem.time_limit_ms,
                    problem.memory_limit_kb,
                    self._settings.algorithm_output_max_bytes,
                ),
                self._settings.algorithm_job_timeout.total_seconds(),
            )
            if result.verdict != AlgorithmVerdict.ACCEPTED.value:
                raise InvalidAlgorithmProblemError(
                    "Эталонное решение не прошло тест",
                    test_position=case.position,
                    verdict=result.verdict,
                )
        template.validated_at = utc_now()
        mark_updated(template, actor_id)
        await self._transaction.commit()
        return template

    async def delete_template(self, problem_id: uuid.UUID, language: str) -> None:
        problem = await self.get_problem(problem_id)
        if problem.status is ContentStatus.PUBLISHED:
            raise ConflictError("Сначала верните задачу в черновик")
        template = require(
            await self._algorithms.get_template(problem_id, language),
            NotFoundError("Шаблон языка не найден"),
        )
        await self._algorithms.delete_template(template)
        await self._transaction.commit()

    async def create_set(
        self, module_id: uuid.UUID, practice_set: PracticeSet, actor_id: uuid.UUID
    ) -> PracticeSet:
        require(await self._modules.get_for_update(module_id), NotFoundError("Модуль не найден"))
        if practice_set.status is ContentStatus.PUBLISHED:
            raise InvalidAlgorithmProblemError("Сначала добавьте задачи, затем опубликуйте набор")
        practice_set.problems = []
        mark_created(practice_set, actor_id)
        self._algorithms.add_set(practice_set)
        # ModuleItem.practice_set — viewonly, ORM не строит по нему порядок flush: без
        # явного flush тут INSERT INTO module_items мог уйти раньше INSERT INTO
        # practice_sets и упасть на FK-ограничении.
        await self._transaction.flush()
        items = await self._modules.list_items(module_id)
        self._modules.add_item(
            next_module_item(
                items, module_id=module_id, actor_id=actor_id, practice_set_id=practice_set.id
            )
        )
        await self._transaction.commit()
        return practice_set

    async def get_set(self, set_id: uuid.UUID) -> PracticeSet:
        return require(
            await self._algorithms.get_set(set_id, published_only=False),
            NotFoundError("Набор практики не найден"),
        )

    async def list_sets(self) -> list[PracticeSet]:
        return await self._algorithms.list_sets()

    async def delete_set(self, set_id: uuid.UUID) -> None:
        await self._algorithms.delete_set(await self.get_set(set_id))
        await self._transaction.commit()

    async def update_set(
        self, set_id: uuid.UUID, changes: dict[str, Any], actor_id: uuid.UUID
    ) -> PracticeSet:
        practice_set = await self.get_set(set_id)
        if changes.get("status") is ContentStatus.PUBLISHED:
            if not practice_set.problems or any(
                item.problem.status is not ContentStatus.PUBLISHED for item in practice_set.problems
            ):
                raise InvalidAlgorithmProblemError("Набор должен содержать опубликованные задачи")
            mode = changes.get("mode", practice_set.mode)
            duration = changes.get("duration_minutes", practice_set.duration_minutes)
            if mode is PracticeMode.MOCK_INTERVIEW and not duration:
                raise InvalidAlgorithmProblemError("Для mock interview укажите длительность")
        validate_required_updates(changes, {"title", "mode", "status"})
        practice_set.title = changes.get("title", practice_set.title)
        practice_set.description = changes.get("description", practice_set.description)
        practice_set.mode = changes.get("mode", practice_set.mode)
        practice_set.duration_minutes = changes.get(
            "duration_minutes", practice_set.duration_minutes
        )
        practice_set.status = changes.get("status", practice_set.status)
        mark_updated(practice_set, actor_id)
        await self._transaction.commit()
        return practice_set

    async def add_set_problem(
        self,
        set_id: uuid.UUID,
        problem_id: uuid.UUID,
        recommended_minutes: int | None,
        actor_id: uuid.UUID,
    ) -> PracticeSetProblem:
        practice_set = await self.get_set(set_id)
        problem = await self.get_problem(problem_id)
        if practice_set.status is ContentStatus.PUBLISHED:
            raise ConflictError("Сначала верните набор в черновик")
        if await self._algorithms.get_set_problem(set_id, problem_id) is not None:
            raise ConflictError("Задача уже входит в набор")
        item = PracticeSetProblem(
            practice_set_id=set_id,
            problem_id=problem_id,
            position=len(practice_set.problems),
            recommended_minutes=recommended_minutes,
            problem=problem,
        )
        mark_created(item, actor_id)
        self._algorithms.add_set_problem(item)
        practice_set.problems.append(item)
        await self._transaction.commit()
        return item

    async def reorder_set(
        self, set_id: uuid.UUID, problem_ids: Sequence[uuid.UUID], actor_id: uuid.UUID
    ) -> None:
        practice_set = await self.get_set(set_id)
        apply_order_by(
            practice_set.problems,
            problem_ids,
            actor_id,
            subject="задачи",
            key=lambda item: item.problem_id,
        )
        await self._transaction.commit()

    async def remove_set_problem(self, set_id: uuid.UUID, problem_id: uuid.UUID) -> None:
        practice_set = await self.get_set(set_id)
        if practice_set.status is ContentStatus.PUBLISHED:
            raise ConflictError("Сначала верните набор в черновик")
        item = require(
            await self._algorithms.get_set_problem(set_id, problem_id),
            NotFoundError("Задача не входит в набор"),
        )
        await self._algorithms.delete_set_problem(item)
        await self._transaction.commit()


@dataclass(frozen=True, slots=True)
class ProblemCatalog:
    """Каталог тренажёра: задачи вместе с прогрессом текущего пользователя."""

    items: list[tuple[AlgorithmProblem, AlgorithmProgress | None]]
    topics: list[str]
    total: int


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
        topic: str | None = None,
        query: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> ProblemCatalog:
        problems, total = await self._algorithms.list_published_problems(
            difficulty=difficulty, topic=topic, query=query, limit=limit, offset=offset
        )
        progress = await self._algorithms.progress_map(user_id, [item.id for item in problems])
        topics = await self._algorithms.published_topics()
        return ProblemCatalog(
            items=[(problem, progress.get(problem.id)) for problem in problems],
            topics=topics,
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
        return progress or _new_progress(user_id, problem_id)

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
            progress = _new_progress(
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


class AlgorithmWorkerService:
    def __init__(
        self,
        transaction: Transaction,
        algorithms: AlgorithmWorkerRepositoryPort,
        runner: CodeRunner,
        settings: Settings,
    ) -> None:
        self._transaction, self._algorithms, self._runner, self._settings = (
            transaction,
            algorithms,
            runner,
            settings,
        )

    async def process_next(self) -> bool:
        submission = await self._algorithms.claim_submission(
            stale_before=utc_now() - self._settings.algorithm_job_timeout
        )
        if submission is None:
            return False
        submission.status, submission.claimed_at = SubmissionStatus.RUNNING, utc_now()
        await self._transaction.commit()
        try:
            await self._execute(submission)
        except Exception:  # runner details must never leak through the student API
            submission = await self._algorithms.get_submission(submission.id, for_update=True)
            if submission is not None and submission.status is not SubmissionStatus.FINISHED:
                submission.status, submission.verdict = (
                    SubmissionStatus.FAILED,
                    AlgorithmVerdict.INTERNAL_ERROR,
                )
                submission.safe_error, submission.finished_at = (
                    "Не удалось выполнить код",
                    utc_now(),
                )
                await self._transaction.commit()
        return True

    async def process(self, submission_id: uuid.UUID, *, redelivered: bool = False) -> None:
        """Consume an at-least-once broker message without duplicating execution."""
        submission = await self._algorithms.get_submission(submission_id, for_update=True)
        if submission is None:
            return
        if submission.status in (SubmissionStatus.FINISHED, SubmissionStatus.FAILED):
            return
        if (
            not redelivered
            and submission.status is SubmissionStatus.RUNNING
            and submission.claimed_at is not None
            and submission.claimed_at >= utc_now() - self._settings.algorithm_job_timeout
        ):
            return
        submission.status, submission.claimed_at = SubmissionStatus.RUNNING, utc_now()
        await self._transaction.commit()
        try:
            await self._execute(submission)
        except RunnerUnavailableError:
            locked = await self._algorithms.get_submission(submission_id, for_update=True)
            if locked is not None:
                locked.status = SubmissionStatus.QUEUED
                locked.claimed_at = None
                await self._transaction.commit()
            raise
        except Exception:
            locked = await self._algorithms.get_submission(submission_id, for_update=True)
            if locked is not None:
                locked.status = SubmissionStatus.FAILED
                locked.verdict = AlgorithmVerdict.INTERNAL_ERROR
                locked.safe_error = "Не удалось выполнить код"
                locked.finished_at = utc_now()
                await self._transaction.commit()

    async def _execute(self, submission: AlgorithmSubmission) -> None:
        problem = await self._algorithms.get_problem(submission.problem_id, published_only=False)
        if problem is None:
            raise RuntimeError("problem disappeared")
        if submission.kind is SubmissionKind.RUN:
            cases = (
                [(None, submission.custom_input, None)]
                if submission.custom_input is not None
                else [
                    (case.position, case.input, case.expected_output)
                    for case in problem.test_cases
                    if case.is_sample
                ]
            )
        else:
            cases = [
                (case.position, case.input, case.expected_output)
                for case in problem.test_cases
                if not case.is_sample
            ]
        results: list[CaseResult] = []
        total_runtime, max_memory = 0, 0
        final_verdict = AlgorithmVerdict.ACCEPTED
        failed_test: int | None = None
        for position, stdin, expected in cases:
            job = await self._runner.submit(
                RunRequest(
                    submission.language,
                    submission.source_code,
                    stdin or "",
                    expected,
                    problem.time_limit_ms,
                    problem.memory_limit_kb,
                    self._settings.algorithm_output_max_bytes,
                )
            )
            submission.judge_token = job.id.encode()
            await self._transaction.commit()
            result = await wait_for_result(
                self._runner, job.id, self._settings.algorithm_job_timeout.total_seconds()
            )
            verdict = (
                AlgorithmVerdict(result.verdict)
                if result.verdict in AlgorithmVerdict._value2member_map_
                else AlgorithmVerdict.INTERNAL_ERROR
            )
            stdout = bounded_output(result.stdout, self._settings.algorithm_output_max_bytes)
            stderr = bounded_output(
                result.stderr or result.compile_output, self._settings.algorithm_output_max_bytes
            )
            results.append(
                {
                    "position": position,
                    "verdict": verdict.value,
                    "stdout": stdout,
                    "stderr": stderr,
                    "runtime_ms": result.runtime_ms,
                    "memory_kb": result.memory_kb,
                }
            )
            total_runtime += result.runtime_ms or 0
            max_memory = max(max_memory, result.memory_kb or 0)
            if verdict is not AlgorithmVerdict.ACCEPTED:
                final_verdict, failed_test = verdict, position
                break
        locked_submission = await self._algorithms.get_submission(submission.id, for_update=True)
        if locked_submission is None:
            return
        submission = locked_submission
        submission.status, submission.verdict = SubmissionStatus.FINISHED, final_verdict
        submission.runtime_ms, submission.memory_kb, submission.failed_test = (
            total_runtime,
            max_memory or None,
            failed_test,
        )
        submission.finished_at, submission.judge_token = utc_now(), None
        submission.result_json = (
            {"cases": results} if submission.kind is SubmissionKind.RUN else None
        )
        if submission.kind is SubmissionKind.RUN and len(results) == 1:
            submission.stdout, submission.stderr = results[0]["stdout"], results[0]["stderr"]
        await self._update_progress(submission)
        await self._transaction.commit()

    async def _update_progress(self, submission: AlgorithmSubmission) -> None:
        if submission.kind is not SubmissionKind.SUBMIT or submission.progress_counted:
            return
        progress = await self._algorithms.get_progress(
            submission.user_id, submission.problem_id, for_update=True
        )
        if progress is None:
            progress = _new_progress(
                submission.user_id,
                submission.problem_id,
                status=AlgorithmProgressStatus.ATTEMPTED,
            )
            self._algorithms.add_progress(progress)
        progress.attempts += 1
        progress.last_attempt_at = submission.finished_at
        progress.last_counted_submission_id = submission.id
        if submission.verdict is AlgorithmVerdict.ACCEPTED:
            progress.status = AlgorithmProgressStatus.SOLVED
            progress.first_solved_at = progress.first_solved_at or submission.finished_at
        elif progress.status is AlgorithmProgressStatus.UNSEEN:
            progress.status = AlgorithmProgressStatus.ATTEMPTED
        submission.progress_counted = True


def _new_progress(
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
        last_counted_submission_id=None,
    )


def _validate_problem_source(problem: AlgorithmProblem, *, require_statement: bool) -> None:
    """Условие для internal нужно только к публикации — черновик пишут постепенно."""
    if (
        require_statement
        and problem.provider is AlgorithmProvider.INTERNAL
        and not problem.statement_md.strip()
    ):
        raise InvalidAlgorithmProblemError("Для внутренней задачи требуется условие")
    if problem.provider is not AlgorithmProvider.INTERNAL and (
        not problem.external_url or not problem.external_url.startswith("https://")
    ):
        raise InvalidAlgorithmProblemError("Внешняя ссылка должна использовать HTTPS")


def _ensure_publishable(problem: AlgorithmProblem) -> None:
    if problem.provider is not AlgorithmProvider.INTERNAL:
        return
    if not any(case.is_sample for case in problem.test_cases):
        raise InvalidAlgorithmProblemError("Добавьте хотя бы один публичный пример")
    if not any(not case.is_sample for case in problem.test_cases):
        raise InvalidAlgorithmProblemError("Добавьте хотя бы один скрытый тест")
    if not any(template.validated_at is not None for template in problem.templates):
        raise InvalidAlgorithmProblemError("Проверьте эталонное решение хотя бы для одного языка")


def _invalidate_templates(problem: AlgorithmProblem) -> None:
    for template in problem.templates:
        template.validated_at = None


class AlgorithmDispatchService:
    def __init__(
        self,
        transaction: Transaction,
        algorithms: AlgorithmDispatchRepositoryPort,
        queue: SubmissionQueue,
    ) -> None:
        self._transaction = transaction
        self._algorithms = algorithms
        self._queue = queue

    async def dispatch_next(self) -> bool:
        event = await self._algorithms.claim_outbox()
        if event is None:
            return False
        await self._queue.publish(event.submission_id)
        event.dispatched_at = utc_now()
        event.attempts += 1
        event.last_error = None
        await self._transaction.commit()
        return True


class AlgorithmOperationsService:
    def __init__(self, algorithms: AlgorithmOperationsRepositoryPort, runner: CodeRunner) -> None:
        self._algorithms = algorithms
        self._runner = runner

    async def health(self) -> tuple[str, int]:
        try:
            languages = await self._runner.languages()
        except RunnerUnavailableError:
            return "unavailable", 0
        expected = 8
        return ("healthy" if len(languages) == expected else "degraded"), len(languages)

    async def languages(self) -> list[RunnerLanguage]:
        return await self._runner.languages()

    async def queue(self) -> tuple[int, int, int]:
        return await self._algorithms.queue_stats()
