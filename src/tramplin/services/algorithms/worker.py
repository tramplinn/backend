import uuid_utils.compat as uuid

from tramplin.core.config import Settings
from tramplin.core.errors import RunnerUnavailableError
from tramplin.core.time import utc_now
from tramplin.models.algorithms import AlgorithmSubmission
from tramplin.models.enums import (
    AlgorithmProgressStatus,
    AlgorithmVerdict,
    SubmissionKind,
    SubmissionStatus,
)
from tramplin.services.algorithm_execution import CaseResult, bounded_output, wait_for_result
from tramplin.services.algorithm_ports import AlgorithmWorkerRepositoryPort
from tramplin.services.algorithms.practice import new_progress
from tramplin.services.contracts import CodeRunner, RunRequest, Transaction


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
            progress = new_progress(
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
            # Только последнее принятое решение подставляем при следующем открытии задачи.
            progress.last_solution_language = submission.language
            progress.last_solution_code = submission.source_code
        elif progress.status is AlgorithmProgressStatus.UNSEEN:
            progress.status = AlgorithmProgressStatus.ATTEMPTED
        submission.progress_counted = True
