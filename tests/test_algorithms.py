from collections.abc import Sequence
from datetime import timedelta
from typing import Any

import pytest

from tramplin.api.algorithm_mapping import (
    problem_author_out,
    problem_card_out,
    problem_out,
    set_out,
    submission_out,
)
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
from tramplin.models.base import new_id
from tramplin.models.content import Module
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
from tramplin.models.tags import Tag
from tramplin.services.algorithm_execution import bounded_output
from tramplin.services.algorithms import (
    AlgorithmAuthoringService,
    AlgorithmDispatchService,
    AlgorithmPracticeService,
    AlgorithmWorkerService,
)
from tramplin.services.contracts import RunnerJob, RunnerLanguage, RunRequest, RunResult


class TransactionFake:
    def __init__(self) -> None:
        self.commits = 0
        self.flushes = 0

    async def commit(self) -> None:
        self.commits += 1

    async def flush(self) -> None:
        self.flushes += 1


class RunnerFake:
    def __init__(self, results: list[RunResult] | None = None) -> None:
        self.requests: list[RunRequest] = []
        self.results = results or [RunResult("accepted", stdout="ok\n", runtime_ms=4, memory_kb=12)]

    async def languages(self) -> list[RunnerLanguage]:
        return [RunnerLanguage("python", "Python 3")]

    async def submit(self, request: RunRequest) -> RunnerJob:
        self.requests.append(request)
        return RunnerJob(str(len(self.requests)))

    async def result(self, job_id: str) -> RunResult | None:
        return self.results[min(int(job_id) - 1, len(self.results) - 1)]


class AlgorithmsFake:
    def __init__(self) -> None:
        self.problems: dict[Any, AlgorithmProblem] = {}
        self.cases: dict[Any, AlgorithmTestCase] = {}
        self.templates: dict[tuple[Any, str], AlgorithmTemplate] = {}
        self.sets: dict[Any, PracticeSet] = {}
        self.sessions: dict[Any, PracticeSession] = {}
        self.submissions: dict[Any, AlgorithmSubmission] = {}
        self.progress: dict[tuple[Any, Any], AlgorithmProgress] = {}
        self.outbox: dict[Any, AlgorithmJobOutbox] = {}
        self.hour_count = 0
        self.problem_count = 0

    async def list_problems(self) -> list[AlgorithmProblem]:
        return list(self.problems.values())

    async def list_published_problems(
        self,
        *,
        difficulty: AlgorithmDifficulty | None,
        tag_id: Any | None,
        query: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[AlgorithmProblem], int]:
        items = [
            problem
            for problem in self.problems.values()
            if problem.status is ContentStatus.PUBLISHED
            and (difficulty is None or problem.difficulty is difficulty)
            and (tag_id is None or tag_id in {tag.id for tag in problem.tags})
            and (not query or query.lower() in problem.title.lower())
        ]
        return items[offset : offset + limit], len(items)

    async def published_tags(self) -> list[Tag]:
        seen: dict[Any, Tag] = {}
        for problem in self.problems.values():
            if problem.status is ContentStatus.PUBLISHED:
                for tag in problem.tags:
                    seen[tag.id] = tag
        return sorted(seen.values(), key=lambda tag: tag.name)

    async def progress_map(
        self, user_id: Any, problem_ids: Sequence[Any]
    ) -> dict[Any, AlgorithmProgress]:
        wanted = set(problem_ids)
        return {
            problem_id: value
            for (owner, problem_id), value in self.progress.items()
            if owner == user_id and problem_id in wanted
        }

    async def get_problem(
        self, problem_id: Any, *, published_only: bool
    ) -> AlgorithmProblem | None:
        value = self.problems.get(problem_id)
        return (
            value
            if value and (not published_only or value.status is ContentStatus.PUBLISHED)
            else None
        )

    def add_problem(self, problem: AlgorithmProblem) -> AlgorithmProblem:
        self.problems[problem.id] = problem
        return problem

    async def delete_problem(self, problem: AlgorithmProblem) -> None:
        del self.problems[problem.id]

    async def get_test_case(self, case_id: Any) -> AlgorithmTestCase | None:
        return self.cases.get(case_id)

    def add_test_case(self, case: AlgorithmTestCase) -> AlgorithmTestCase:
        self.cases[case.id] = case
        return case

    async def delete_test_case(self, case: AlgorithmTestCase) -> None:
        self.cases.pop(case.id)
        case.problem.test_cases.remove(case)

    async def get_template(self, problem_id: Any, language: str) -> AlgorithmTemplate | None:
        return self.templates.get((problem_id, language))

    def add_template(self, template: AlgorithmTemplate) -> AlgorithmTemplate:
        self.templates[(template.problem_id, template.language)] = template
        return template

    async def delete_template(self, template: AlgorithmTemplate) -> None:
        self.templates.pop((template.problem_id, template.language))

    async def get_set(self, set_id: Any, *, published_only: bool) -> PracticeSet | None:
        value = self.sets.get(set_id)
        return (
            value
            if value and (not published_only or value.status is ContentStatus.PUBLISHED)
            else None
        )

    def add_set(self, practice_set: PracticeSet) -> PracticeSet:
        self.sets[practice_set.id] = practice_set
        return practice_set

    async def list_sets(self) -> list[PracticeSet]:
        return list(self.sets.values())

    async def delete_set(self, practice_set: PracticeSet) -> None:
        del self.sets[practice_set.id]

    def add_set_problem(self, item: PracticeSetProblem) -> PracticeSetProblem:
        return item

    async def delete_set_problem(self, item: PracticeSetProblem) -> None:
        item.practice_set.problems.remove(item)

    async def get_set_problem(self, set_id: Any, problem_id: Any) -> PracticeSetProblem | None:
        practice_set = self.sets.get(set_id)
        return (
            next((item for item in practice_set.problems if item.problem_id == problem_id), None)
            if practice_set
            else None
        )

    def add_session(self, session: PracticeSession) -> PracticeSession:
        session.practice_set = (
            self.sets[session.practice_set_id] if session.practice_set_id is not None else None
        )
        self.sessions[session.id] = session
        return session

    async def get_session(
        self, session_id: Any, *, for_update: bool = False
    ) -> PracticeSession | None:
        return self.sessions.get(session_id)

    async def lock_user(self, user_id: Any) -> None:
        return None

    def add_submission(self, submission: AlgorithmSubmission) -> AlgorithmSubmission:
        submission.created_at = utc_now()
        self.submissions[submission.id] = submission
        return submission

    def add_outbox(self, event: AlgorithmJobOutbox) -> AlgorithmJobOutbox:
        self.outbox[event.submission_id] = event
        return event

    async def claim_outbox(self) -> AlgorithmJobOutbox | None:
        return next((event for event in self.outbox.values() if event.dispatched_at is None), None)

    async def get_submission(
        self, submission_id: Any, *, for_update: bool = False
    ) -> AlgorithmSubmission | None:
        return self.submissions.get(submission_id)

    async def active_submissions(self, user_id: Any) -> int:
        return sum(
            item.user_id == user_id
            and item.status in (SubmissionStatus.QUEUED, SubmissionStatus.RUNNING)
            for item in self.submissions.values()
        )

    async def submission_count(
        self, *, user_id: Any, since: Any = None, session_id: Any = None, problem_id: Any = None
    ) -> int:
        return self.hour_count if since is not None else self.problem_count

    async def claim_submission(self, *, stale_before: Any) -> AlgorithmSubmission | None:
        return next(
            (item for item in self.submissions.values() if item.status is SubmissionStatus.QUEUED),
            None,
        )

    async def get_progress(
        self, user_id: Any, problem_id: Any, *, for_update: bool = False
    ) -> AlgorithmProgress | None:
        return self.progress.get((user_id, problem_id))

    def add_progress(self, progress: AlgorithmProgress) -> AlgorithmProgress:
        self.progress[(progress.user_id, progress.problem_id)] = progress
        return progress


class ModulesFake:
    def __init__(self) -> None:
        self.module = Module(course_id=new_id(), title="M", slug="m", position=0)
        self.items: list[Any] = []

    async def get_for_update(self, module_id: Any) -> Module | None:
        return self.module if module_id == self.module.id else None

    async def list_items(self, module_id: Any) -> list[Any]:
        return self.items

    def add_item(self, item: Any) -> Any:
        self.items.append(item)
        return item


class TagsFake:
    def __init__(self) -> None:
        self.by_key: dict[str, Tag] = {}

    async def list_all(self) -> list[Tag]:
        return sorted(self.by_key.values(), key=lambda tag: tag.name)

    async def get_or_create_many(self, names: Sequence[str]) -> list[Tag]:
        resolved: list[Tag] = []
        seen: set[str] = set()
        for raw in names:
            name = raw.strip()
            if not name:
                continue
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            tag = self.by_key.get(key)
            if tag is None:
                tag = Tag(name=name)
                self.by_key[key] = tag
            resolved.append(tag)
        return resolved


def problem(
    *,
    status: ContentStatus = ContentStatus.DRAFT,
    provider: AlgorithmProvider = AlgorithmProvider.INTERNAL,
) -> AlgorithmProblem:
    prob = AlgorithmProblem(
        provider=provider,
        external_key=None,
        external_url=None,
        title="Two sum",
        statement_md="# Solve",
        statement_html="",
        difficulty=AlgorithmDifficulty.EASY,
        time_limit_ms=1000,
        memory_limit_kb=262144,
        status=status,
    )
    prob.tags = [Tag(name="arrays")]
    return prob


def published_course(
    repo: AlgorithmsFake, mode: PracticeMode = PracticeMode.PRACTICE
) -> tuple[AlgorithmProblem, PracticeSet]:
    task = problem(status=ContentStatus.PUBLISHED)
    task.test_cases = [
        AlgorithmTestCase(
            problem_id=task.id,
            position=0,
            input="1\n",
            expected_output="2\n",
            is_sample=True,
            weight=1,
        )
    ]
    task.templates = [
        AlgorithmTemplate(
            problem_id=task.id,
            language="python",
            starter_code="# code",
            solution_code="print(2)",
            validated_at=utc_now(),
        )
    ]
    practice_set = PracticeSet(
        title="Set",
        description="D",
        mode=mode,
        duration_minutes=1 if mode is PracticeMode.MOCK_INTERVIEW else None,
        status=ContentStatus.PUBLISHED,
    )
    link = PracticeSetProblem(
        practice_set_id=practice_set.id,
        problem_id=task.id,
        position=0,
        recommended_minutes=10,
        problem=task,
    )
    practice_set.problems = [link]
    repo.problems[task.id] = task
    repo.sets[practice_set.id] = practice_set
    return task, practice_set


async def test_authoring_problem_cases_templates_and_publication(settings: Any) -> None:
    tx, repo, modules, runner = TransactionFake(), AlgorithmsFake(), ModulesFake(), RunnerFake()
    service = AlgorithmAuthoringService(tx, repo, modules, runner, settings, TagsFake())
    actor = new_id()
    task = await service.create_problem(problem(), ["arrays"], actor)
    assert task.statement_html.startswith("<h1>")
    assert await service.get_problem(task.id) is task

    sample = await service.add_case(
        task.id,
        AlgorithmTestCase(
            problem_id=task.id, position=0, input="1", expected_output="2", is_sample=True, weight=1
        ),
        actor,
    )
    hidden = await service.add_case(
        task.id,
        AlgorithmTestCase(
            problem_id=task.id,
            position=1,
            input="2",
            expected_output="4",
            is_sample=False,
            weight=1,
        ),
        actor,
    )
    repo.cases[sample.id], repo.cases[hidden.id] = sample, hidden
    await service.update_case(sample.id, {"input": "1\n"}, actor)
    template = await service.put_template(
        task.id, "python", "# start", "print(int(input())*2)", actor
    )
    assert template.validated_at is None
    await service.validate_template(task.id, "python", actor)
    assert len(runner.requests) == 2
    await service.update_problem(task.id, {"status": ContentStatus.PUBLISHED}, actor)
    assert task.status is ContentStatus.PUBLISHED
    with pytest.raises(ConflictError):
        await service.update_case(sample.id, {"input": "x"}, actor)
    await service.update_problem(task.id, {"status": ContentStatus.DRAFT}, actor)
    await service.delete_case(hidden.id)
    await service.delete_problem(task.id)
    with pytest.raises(NotFoundError):
        await service.get_problem(task.id)


async def test_authoring_rejects_invalid_problem_and_reference(settings: Any) -> None:
    repo = AlgorithmsFake()
    service = AlgorithmAuthoringService(
        TransactionFake(),
        repo,
        ModulesFake(),
        RunnerFake([RunResult("wrong_answer")]),
        settings,
        TagsFake(),
    )
    actor = new_id()
    external = problem(provider=AlgorithmProvider.EXTERNAL)
    external.statement_md = ""
    with pytest.raises(InvalidAlgorithmProblemError, match="HTTPS"):
        await service.create_problem(external, [], actor)
    task = await service.create_problem(problem(), ["arrays"], actor)
    with pytest.raises(InvalidAlgorithmProblemError, match="публичный"):
        await service.update_problem(task.id, {"status": ContentStatus.PUBLISHED}, actor)
    task.status = ContentStatus.DRAFT
    task.test_cases = [
        AlgorithmTestCase(
            problem_id=task.id, position=0, input="", expected_output="", is_sample=True, weight=1
        )
    ]
    template = await service.put_template(task.id, "python", "", "bad", actor)
    with pytest.raises(InvalidAlgorithmProblemError, match="не прошло"):
        await service.validate_template(task.id, "python", actor)
    assert template.validated_at is None


async def test_authoring_practice_set_and_order(settings: Any) -> None:
    repo, modules = AlgorithmsFake(), ModulesFake()
    service = AlgorithmAuthoringService(
        TransactionFake(), repo, modules, RunnerFake(), settings, TagsFake()
    )
    actor = new_id()
    practice_set = await service.create_set(
        modules.module.id,
        PracticeSet(
            title="Set",
            description="",
            mode=PracticeMode.MOCK_INTERVIEW,
            duration_minutes=20,
            status=ContentStatus.DRAFT,
        ),
        actor,
    )
    first, second = problem(status=ContentStatus.PUBLISHED), problem(status=ContentStatus.PUBLISHED)
    repo.problems[first.id], repo.problems[second.id] = first, second
    await service.add_set_problem(practice_set.id, first.id, 5, actor)
    await service.add_set_problem(practice_set.id, second.id, None, actor)
    with pytest.raises(ConflictError):
        await service.add_set_problem(practice_set.id, first.id, 5, actor)
    await service.reorder_set(practice_set.id, [second.id, first.id], actor)
    assert [
        item.problem_id for item in sorted(practice_set.problems, key=lambda item: item.position)
    ] == [second.id, first.id]
    await service.update_set(practice_set.id, {"status": ContentStatus.PUBLISHED}, actor)
    assert modules.items[0].practice_set_id == practice_set.id


async def test_student_session_enqueue_limits_and_reflection(settings: Any) -> None:
    tx, repo = TransactionFake(), AlgorithmsFake()
    task, practice_set = published_course(repo)
    service = AlgorithmPracticeService(tx, repo, settings)
    user = new_id()
    session = await service.start_session(practice_set.id, user)
    assert session.deadline_at is None
    run = await service.enqueue(
        session.id, task.id, user, SubmissionKind.RUN, "python", "print(2)", "1"
    )
    assert run.status is SubmissionStatus.QUEUED
    with pytest.raises(RunnerBusyError):
        await service.enqueue(session.id, task.id, user, SubmissionKind.RUN, "python", "x")
    run.status = SubmissionStatus.FINISHED
    with pytest.raises(InvalidAlgorithmProblemError, match="Язык"):
        await service.enqueue(session.id, task.id, user, SubmissionKind.RUN, "java", "x")
    repo.hour_count = settings.algorithm_runs_per_hour
    with pytest.raises(TooManyRequestsError, match="за час"):
        await service.enqueue(session.id, task.id, user, SubmissionKind.RUN, "python", "x")
    repo.hour_count = 0
    progress = await service.get_progress(task.id, user)
    assert progress.status is AlgorithmProgressStatus.UNSEEN
    progress = await service.update_reflection(task.id, user, "O(n)", 4, "ok")
    assert progress.confidence == 4
    await service.complete_session(session.id, user, "done")
    with pytest.raises(SessionExpiredError):
        await service.enqueue(session.id, task.id, user, SubmissionKind.SUBMIT, "python", "x")


async def test_catalog_lists_published_with_progress(settings: Any) -> None:
    repo = AlgorithmsFake()
    task, _ = published_course(repo)
    hidden = problem()
    repo.problems[hidden.id] = hidden
    service = AlgorithmPracticeService(TransactionFake(), repo, settings)
    user = new_id()

    catalog = await service.list_catalog(user)
    assert [item.id for item, _ in catalog.items] == [task.id]
    assert [tag.name for tag in catalog.tags] == ["arrays"]
    assert catalog.total == 1
    assert catalog.items[0][1] is None

    repo.progress[(user, task.id)] = AlgorithmProgress(
        user_id=user,
        problem_id=task.id,
        status=AlgorithmProgressStatus.SOLVED,
        attempts=3,
        hints_used=0,
        first_solved_at=utc_now(),
        last_attempt_at=utc_now(),
        confidence=None,
        complexity_md=None,
        reflection_md=None,
        last_counted_submission_id=None,
    )
    catalog = await service.list_catalog(user)
    card = problem_card_out(*catalog.items[0])
    assert card.solved is True
    assert card.attempts == 3
    assert card.languages == ["python"]


async def test_catalog_filters(settings: Any) -> None:
    repo = AlgorithmsFake()
    task, _ = published_course(repo)
    service = AlgorithmPracticeService(TransactionFake(), repo, settings)
    user = new_id()

    assert (await service.list_catalog(user, difficulty=AlgorithmDifficulty.HARD)).total == 0
    assert (await service.list_catalog(user, tag_id=new_id())).total == 0
    assert (await service.list_catalog(user, query="two")).items[0][0].id == task.id
    assert (await service.list_catalog(user, query="нет такой")).total == 0


async def test_free_session_allows_any_published_problem(settings: Any) -> None:
    repo = AlgorithmsFake()
    task, _ = published_course(repo)
    service = AlgorithmPracticeService(TransactionFake(), repo, settings)
    user = new_id()

    session = await service.start_free_session(user)
    assert session.practice_set_id is None
    assert session.deadline_at is None
    assert session.mode is PracticeMode.PRACTICE

    # Задача не входит ни в один набор, но в свободной сессии это разрешено.
    run = await service.enqueue(
        session.id, task.id, user, SubmissionKind.SUBMIT, "python", "print(2)"
    )
    assert run.status is SubmissionStatus.QUEUED


async def test_mock_session_expires(settings: Any) -> None:
    repo = AlgorithmsFake()
    task, practice_set = published_course(repo, PracticeMode.MOCK_INTERVIEW)
    service = AlgorithmPracticeService(TransactionFake(), repo, settings)
    user = new_id()
    session = await service.start_session(practice_set.id, user)
    assert session.deadline_at is not None
    session.deadline_at = utc_now() - timedelta(seconds=1)
    assert (await service.get_session(session.id, user)).status is PracticeSessionStatus.EXPIRED
    with pytest.raises(NotFoundError):
        await service.get_session(session.id, new_id())
    assert await service.get_problem(task.id) is task


async def test_worker_run_and_submit_are_safe_and_idempotent(settings: Any) -> None:
    repo, tx = AlgorithmsFake(), TransactionFake()
    task, practice_set = published_course(repo)
    hidden = AlgorithmTestCase(
        problem_id=task.id,
        position=7,
        input="secret-input",
        expected_output="secret-output",
        is_sample=False,
        weight=1,
    )
    task.test_cases.append(hidden)
    user = new_id()
    session = PracticeSession(
        practice_set_id=practice_set.id,
        user_id=user,
        mode=PracticeMode.PRACTICE,
        status=PracticeSessionStatus.ACTIVE,
        started_at=utc_now(),
        deadline_at=None,
        completed_at=None,
        reflection_md=None,
        practice_set=practice_set,
    )
    repo.sessions[session.id] = session
    submit = AlgorithmSubmission(
        session_id=session.id,
        problem_id=task.id,
        user_id=user,
        kind=SubmissionKind.SUBMIT,
        language="python",
        source_code="print(2)",
        custom_input=None,
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
    repo.add_submission(submit)
    worker = AlgorithmWorkerService(tx, repo, RunnerFake(), settings)
    assert await worker.process_next()
    assert submit.verdict is AlgorithmVerdict.ACCEPTED
    assert repo.progress[(user, task.id)].attempts == 1
    await worker._update_progress(submit)
    assert repo.progress[(user, task.id)].attempts == 1
    payload = submission_out(submit).model_dump_json()
    assert "secret-input" not in payload and "secret-output" not in payload

    run = AlgorithmSubmission(
        session_id=session.id,
        problem_id=task.id,
        user_id=user,
        kind=SubmissionKind.RUN,
        language="python",
        source_code="print(2)",
        custom_input="hello",
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
    repo.add_submission(run)
    assert await worker.process_next()
    output = submission_out(run)
    assert output.stdout == "ok\n" and len(output.cases) == 1
    assert not await worker.process_next()


async def test_worker_stops_on_first_failure_and_maps_internal_error(settings: Any) -> None:
    repo = AlgorithmsFake()
    task, practice_set = published_course(repo)
    task.test_cases.extend(
        [
            AlgorithmTestCase(
                problem_id=task.id,
                position=1,
                input="secret",
                expected_output="no",
                is_sample=False,
                weight=1,
            )
        ]
    )
    user = new_id()
    session = PracticeSession(
        practice_set_id=practice_set.id,
        user_id=user,
        mode=PracticeMode.PRACTICE,
        status=PracticeSessionStatus.ACTIVE,
        started_at=utc_now(),
        deadline_at=None,
        completed_at=None,
        reflection_md=None,
        practice_set=practice_set,
    )
    repo.sessions[session.id] = session
    submission = AlgorithmSubmission(
        session_id=session.id,
        problem_id=task.id,
        user_id=user,
        kind=SubmissionKind.SUBMIT,
        language="python",
        source_code="bad",
        custom_input=None,
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
    repo.add_submission(submission)
    worker = AlgorithmWorkerService(
        TransactionFake(), repo, RunnerFake([RunResult("wrong_answer")]), settings
    )
    await worker.process_next()
    assert submission.verdict is AlgorithmVerdict.WRONG_ANSWER
    assert submission.failed_test == 1
    assert submission.stdout is None and submission.result_json is None


async def test_broker_worker_handles_duplicate_retry_and_poison_jobs(settings: Any) -> None:
    repo, tx = AlgorithmsFake(), TransactionFake()
    task, practice_set = published_course(repo)
    task.test_cases.append(
        AlgorithmTestCase(
            problem_id=task.id,
            position=1,
            input="hidden",
            expected_output="ok\n",
            is_sample=False,
            weight=1,
        )
    )
    user = new_id()
    session = PracticeSession(
        practice_set_id=practice_set.id,
        user_id=user,
        mode=PracticeMode.PRACTICE,
        status=PracticeSessionStatus.ACTIVE,
        started_at=utc_now(),
        deadline_at=None,
        completed_at=None,
        reflection_md=None,
        practice_set=practice_set,
    )
    queued = AlgorithmSubmission(
        session_id=session.id,
        problem_id=task.id,
        user_id=user,
        kind=SubmissionKind.SUBMIT,
        language="python",
        source_code="x",
        custom_input=None,
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
    repo.add_submission(queued)
    worker = AlgorithmWorkerService(tx, repo, RunnerFake(), settings)
    await worker.process(new_id())
    await worker.process(queued.id)
    assert queued.status is SubmissionStatus.FINISHED
    await worker.process(queued.id)  # duplicate delivery is an acknowledged no-op

    fresh_running = AlgorithmSubmission(
        session_id=session.id,
        problem_id=task.id,
        user_id=user,
        kind=SubmissionKind.RUN,
        language="python",
        source_code="x",
        custom_input="",
        status=SubmissionStatus.RUNNING,
        verdict=None,
        runtime_ms=None,
        memory_kb=None,
        failed_test=None,
        stdout=None,
        stderr=None,
        safe_error=None,
        judge_token=None,
        result_json=None,
        claimed_at=utc_now(),
        finished_at=None,
        progress_counted=False,
    )
    repo.add_submission(fresh_running)
    await worker.process(fresh_running.id)
    assert fresh_running.status is SubmissionStatus.RUNNING
    await worker.process(fresh_running.id, redelivered=True)
    assert repo.submissions[fresh_running.id].status is SubmissionStatus.FINISHED

    missing_problem = AlgorithmSubmission(
        session_id=session.id,
        problem_id=new_id(),
        user_id=user,
        kind=SubmissionKind.RUN,
        language="python",
        source_code="x",
        custom_input="",
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
    repo.add_submission(missing_problem)
    await worker.process(missing_problem.id)
    assert missing_problem.status is SubmissionStatus.FAILED
    assert missing_problem.safe_error == "Не удалось выполнить код"


async def test_broker_worker_requeues_runner_outage(settings: Any) -> None:
    repo = AlgorithmsFake()
    task, practice_set = published_course(repo)
    user = new_id()
    session = PracticeSession(
        practice_set_id=practice_set.id,
        user_id=user,
        mode=PracticeMode.PRACTICE,
        status=PracticeSessionStatus.ACTIVE,
        started_at=utc_now(),
        deadline_at=None,
        completed_at=None,
        reflection_md=None,
        practice_set=practice_set,
    )
    submission = AlgorithmSubmission(
        session_id=session.id,
        problem_id=task.id,
        user_id=user,
        kind=SubmissionKind.RUN,
        language="python",
        source_code="x",
        custom_input="x",
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
    repo.add_submission(submission)

    class UnavailableRunner(RunnerFake):
        async def submit(self, request: RunRequest) -> RunnerJob:
            raise RunnerUnavailableError()

    worker = AlgorithmWorkerService(TransactionFake(), repo, UnavailableRunner(), settings)
    with pytest.raises(RunnerUnavailableError):
        await worker.process(submission.id)
    assert submission.status is SubmissionStatus.QUEUED and submission.claimed_at is None


def test_algorithm_mappings_never_expose_hidden_cases() -> None:
    repo = AlgorithmsFake()
    task, practice_set = published_course(repo)
    task.test_cases.append(
        AlgorithmTestCase(
            problem_id=task.id,
            position=1,
            input="hidden",
            expected_output="secret",
            is_sample=False,
            weight=1,
        )
    )
    assert len(problem_author_out(task).test_cases) == 2
    student = problem_out(task)
    assert len(student.samples) == 1
    assert "hidden" not in student.model_dump_json()
    assert set_out(practice_set).problems[0].title == task.title
    truncated = bounded_output("é" * 20, 5)
    assert truncated is not None and truncated.endswith("output truncated")
    assert bounded_output(None, 5) is None


async def test_transactional_outbox_dispatches_once() -> None:
    repo, tx = AlgorithmsFake(), TransactionFake()
    submission_id = new_id()
    event = AlgorithmJobOutbox(
        submission_id=submission_id,
        dispatched_at=None,
        attempts=0,
        last_error="old",
    )
    repo.outbox[submission_id] = event

    class QueueFake:
        def __init__(self) -> None:
            self.messages: list[Any] = []

        async def publish(self, value: Any) -> None:
            self.messages.append(value)

    queue = QueueFake()
    dispatch = AlgorithmDispatchService(tx, repo, queue)
    assert await dispatch.dispatch_next()
    assert queue.messages == [submission_id]
    assert event.dispatched_at is not None and event.attempts == 1 and event.last_error is None
    assert not await dispatch.dispatch_next()


def test_algorithm_job_outbox_uow_sort_order() -> None:
    """SQLAlchemy UOW должен сохранять submission раньше outbox, чтобы не нарушать FK."""
    from sqlalchemy.orm import Session, attributes
    from sqlalchemy.orm.unitofwork import UOWTransaction
    from sqlalchemy.util import topological

    sess = Session()
    sub = AlgorithmSubmission(
        session_id=new_id(),
        problem_id=new_id(),
        user_id=new_id(),
        kind=SubmissionKind.RUN,
        language="python",
        source_code="print(1)",
        status=SubmissionStatus.QUEUED,
        progress_counted=False,
    )
    outbox = AlgorithmJobOutbox(submission_id=sub.id, attempts=0)
    sess.add(sub)
    sess.add(outbox)

    uow = UOWTransaction(sess)
    for obj in (sub, outbox):
        uow.register_object(attributes.instance_state(obj))

    actions = sorted(uow._generate_actions(), key=lambda item: item.sort_key)  # type: ignore[no-untyped-call]
    sorted_rec = list(topological.sort(uow.dependencies, actions))
    save_actions = [rec for rec in sorted_rec if "SaveUpdate" in str(rec)]
    assert len(save_actions) == 2
    assert "AlgorithmSubmission" in str(save_actions[0])
    assert "AlgorithmJobOutbox" in str(save_actions[1])
