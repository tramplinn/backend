from tramplin.api.schemas.algorithms import (
    FailedCaseOut,
    PracticeSetOut,
    ProblemAuthorOut,
    ProblemCardOut,
    ProblemOut,
    RunCaseOut,
    SampleCaseOut,
    SetProblemOut,
    SolutionOut,
    SubmissionOut,
    TemplateAuthorOut,
    TemplateStudentOut,
    TestCaseOut,
)
from tramplin.api.tag_mapping import tags_out
from tramplin.models.algorithms import (
    AlgorithmProblem,
    AlgorithmProgress,
    AlgorithmSubmission,
    PracticeSet,
)
from tramplin.models.enums import AlgorithmProgressStatus


def problem_author_out(problem: AlgorithmProblem) -> ProblemAuthorOut:
    return ProblemAuthorOut(
        id=problem.id,
        slug=problem.slug,
        provider=problem.provider,
        external_key=problem.external_key,
        external_url=problem.external_url,
        title=problem.title,
        statement_md=problem.statement_md,
        statement_html=problem.statement_html,
        difficulty=problem.difficulty,
        tags=tags_out(problem.tags),
        time_limit_ms=problem.time_limit_ms,
        memory_limit_kb=problem.memory_limit_kb,
        status=problem.status,
        test_cases=[TestCaseOut.model_validate(case) for case in problem.test_cases],
        templates=[TemplateAuthorOut.model_validate(template) for template in problem.templates],
    )


def problem_out(problem: AlgorithmProblem) -> ProblemOut:
    return ProblemOut(
        id=problem.id,
        provider=problem.provider,
        external_key=problem.external_key,
        external_url=problem.external_url,
        title=problem.title,
        statement_html=problem.statement_html,
        difficulty=problem.difficulty,
        tags=tags_out(problem.tags),
        time_limit_ms=problem.time_limit_ms,
        memory_limit_kb=problem.memory_limit_kb,
        samples=[
            SampleCaseOut.model_validate(case) for case in problem.test_cases if case.is_sample
        ],
        templates=[TemplateStudentOut.model_validate(template) for template in problem.templates],
    )


def problem_card_out(
    problem: AlgorithmProblem, progress: AlgorithmProgress | None
) -> ProblemCardOut:
    status = progress.status if progress else AlgorithmProgressStatus.UNSEEN
    return ProblemCardOut(
        id=problem.id,
        title=problem.title,
        difficulty=problem.difficulty,
        tags=tags_out(problem.tags),
        provider=problem.provider,
        external_url=problem.external_url,
        languages=[template.language for template in problem.templates],
        status=status,
        attempts=progress.attempts if progress else 0,
        solved=status is AlgorithmProgressStatus.SOLVED,
    )


def set_out(practice_set: PracticeSet) -> PracticeSetOut:
    return PracticeSetOut(
        id=practice_set.id,
        title=practice_set.title,
        description=practice_set.description,
        mode=practice_set.mode,
        duration_minutes=practice_set.duration_minutes,
        status=practice_set.status,
        problems=[
            SetProblemOut(
                problem_id=item.problem_id,
                position=item.position,
                recommended_minutes=item.recommended_minutes,
                title=item.problem.title,
                difficulty=item.problem.difficulty,
            )
            for item in practice_set.problems
        ],
    )


def submission_out(submission: AlgorithmSubmission) -> SubmissionOut:
    raw_cases = submission.result_json.get("cases", []) if submission.result_json else []
    cases = (
        [RunCaseOut.model_validate(case) for case in raw_cases if isinstance(case, dict)]
        if isinstance(raw_cases, list)
        else []
    )
    raw_failed_case = submission.result_json.get("failed_case") if submission.result_json else None
    failed_case = (
        FailedCaseOut.model_validate(raw_failed_case) if isinstance(raw_failed_case, dict) else None
    )
    return SubmissionOut(
        id=submission.id,
        session_id=submission.session_id,
        problem_id=submission.problem_id,
        kind=submission.kind,
        language=submission.language,
        status=submission.status,
        verdict=submission.verdict,
        runtime_ms=submission.runtime_ms,
        memory_kb=submission.memory_kb,
        failed_test=submission.failed_test,
        stdout=submission.stdout if submission.kind.value == "run" else None,
        stderr=submission.stderr if submission.kind.value == "run" else None,
        safe_error=submission.safe_error,
        cases=cases if submission.kind.value == "run" else [],
        failed_case=failed_case if submission.kind.value == "submit" else None,
        created_at=submission.created_at,
        finished_at=submission.finished_at,
    )


def solution_out(submission: AlgorithmSubmission) -> SolutionOut:
    return SolutionOut(
        id=submission.id,
        language=submission.language,
        source_code=submission.source_code,
        finished_at=submission.finished_at,
    )
