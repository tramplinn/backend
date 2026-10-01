from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, cast

import pytest
import uuid_utils.compat as uuid

from tests.fakes import FakeSession
from tramplin.api.schemas.algorithm_plans import AlgorithmPlanApply
from tramplin.core.errors import InvalidPlanError
from tramplin.models.algorithms import AlgorithmProblem, AlgorithmTemplate, AlgorithmTestCase
from tramplin.models.tags import Tag
from tramplin.services.algorithm_plans import AlgorithmPlanService


class AlgorithmRepoFake:
    def __init__(self) -> None:
        self.problems: dict[uuid.UUID, AlgorithmProblem] = {}
        self.cases: dict[uuid.UUID, AlgorithmTestCase] = {}
        self.templates: dict[tuple[uuid.UUID, str], AlgorithmTemplate] = {}

    async def get_problem_by_slug(self, slug: str) -> AlgorithmProblem | None:
        return next((p for p in self.problems.values() if p.slug == slug), None)

    def add_problem(self, problem: AlgorithmProblem) -> AlgorithmProblem:
        self.problems[problem.id] = problem
        return problem

    def add_test_case(self, case: AlgorithmTestCase) -> AlgorithmTestCase:
        self.cases[case.id] = case
        return case

    def add_template(self, template: AlgorithmTemplate) -> AlgorithmTemplate:
        self.templates[(template.problem_id, template.language)] = template
        return template


class TagsFake:
    def __init__(self) -> None:
        self.by_key: dict[str, Tag] = {}

    async def get_or_create_many(self, names: Sequence[str]) -> list[Tag]:
        resolved: list[Tag] = []
        for raw in names:
            name = raw.strip()
            if not name:
                continue
            key = name.lower()
            tag = self.by_key.setdefault(key, Tag(name=name))
            resolved.append(tag)
        return resolved


def make_service() -> tuple[AlgorithmPlanService, FakeSession, AlgorithmRepoFake]:
    transaction = FakeSession()
    algorithms = AlgorithmRepoFake()
    service = AlgorithmPlanService(transaction, cast(Any, algorithms), cast(Any, TagsFake()))
    return service, transaction, algorithms


def problem_plan() -> dict[str, Any]:
    return {
        "problems": [
            {
                "slug": "two-sum",
                "title": "Two Sum",
                "statement_md": "Найдите два числа...",
                "difficulty": "easy",
                "tags": ["arrays"],
                "test_cases": [
                    {"position": 0, "input": "1 2", "expected_output": "3", "is_sample": True},
                    {"position": 1, "input": "5 5", "expected_output": "10"},
                ],
                "templates": [
                    {"language": "python", "starter_code": "def solve():", "solution_code": ""}
                ],
            }
        ]
    }


async def test_apply_creates_problem_with_cases_and_templates() -> None:
    service, transaction, algorithms = make_service()
    plan = AlgorithmPlanApply.model_validate(problem_plan())

    problems, stats = await service.apply(plan, uuid.uuid7())

    assert stats.created == 4  # problem + 2 cases + 1 template
    assert transaction.commits == 1
    problem = problems[0]
    assert problem.slug == "two-sum"
    assert problem.status.value == "draft"
    assert [tag.name for tag in problem.tags] == ["arrays"]
    assert len(algorithms.cases) == 2
    assert len(algorithms.templates) == 1


async def test_apply_matches_by_slug_and_is_idempotent_then_updates() -> None:
    service, _, algorithms = make_service()
    plan = AlgorithmPlanApply.model_validate(problem_plan())
    problems, _ = await service.apply(plan, uuid.uuid7())
    problem = problems[0]

    unchanged_plan = AlgorithmPlanApply.model_validate(problem_plan())
    _, stats = await service.apply(unchanged_plan, uuid.uuid7())
    assert stats.created == 0
    assert stats.updated == 0
    assert stats.unchanged == 4

    changed = problem_plan()
    changed["problems"][0]["title"] = "Two Sum (updated)"
    changed["problems"][0]["test_cases"][0]["expected_output"] = "99"
    _, stats = await service.apply(AlgorithmPlanApply.model_validate(changed), uuid.uuid7())
    assert stats.updated == 2  # problem title + one test case
    assert stats.unchanged == 2  # second case + template
    assert problem.title == "Two Sum (updated)"
    assert len(algorithms.problems) == 1


async def test_apply_is_additive_for_test_cases_outside_plan() -> None:
    service, _, _ = make_service()
    plan = AlgorithmPlanApply.model_validate(problem_plan())
    problems, _ = await service.apply(plan, uuid.uuid7())
    problem = problems[0]
    assert len(problem.test_cases) == 2

    slimmer = problem_plan()
    slimmer["problems"][0]["test_cases"] = [slimmer["problems"][0]["test_cases"][0]]
    await service.apply(AlgorithmPlanApply.model_validate(slimmer), uuid.uuid7())

    assert len(problem.test_cases) == 2


async def test_apply_invalidates_template_validation_on_case_change() -> None:
    service, _, _ = make_service()
    plan = AlgorithmPlanApply.model_validate(problem_plan())
    problems, _ = await service.apply(plan, uuid.uuid7())
    problem = problems[0]
    problem.templates[0].validated_at = datetime(2026, 1, 1, tzinfo=UTC)

    changed = problem_plan()
    changed["problems"][0]["test_cases"][0]["expected_output"] = "42"
    await service.apply(AlgorithmPlanApply.model_validate(changed), uuid.uuid7())

    assert problem.templates[0].validated_at is None


async def test_preview_reports_changes_without_commit() -> None:
    service, transaction, _ = make_service()

    report = await service.preview(AlgorithmPlanApply.model_validate(problem_plan()), uuid.uuid7())

    assert transaction.commits == 0
    assert [(change.action, change.path) for change in report.changes] == [
        ("create", "two-sum"),
        ("create", "two-sum/test-cases/0"),
        ("create", "two-sum/test-cases/1"),
        ("create", "two-sum/templates/python"),
    ]
    assert {issue.code for issue in report.issues} == {"missing_solution"}


async def test_update_reports_changed_fields_and_tags() -> None:
    service, _, _ = make_service()
    await service.apply(AlgorithmPlanApply.model_validate(problem_plan()), uuid.uuid7())
    changed = problem_plan()
    changed["problems"][0]["statement_md"] = "Новое условие"
    changed["problems"][0]["tags"] = ["hash"]

    problems, report = await service.apply(AlgorithmPlanApply.model_validate(changed), uuid.uuid7())

    assert report.changes[0].fields == ["statement_md", "tags"]
    assert problems[0].statement_html.startswith("<p>Новое условие")


async def test_invalid_plan_is_rejected_with_issue_codes() -> None:
    service, transaction, _ = make_service()
    plan = problem_plan()
    plan["problems"][0]["provider"] = "external"
    plan["problems"][0]["test_cases"][1]["position"] = 0
    plan["problems"].append(dict(plan["problems"][0]))

    report = service.validate(AlgorithmPlanApply.model_validate(plan))

    assert {issue.code for issue in report.issues if issue.severity == "error"} == {
        "duplicate_problem",
        "missing_external_url",
        "duplicate_test_case_position",
    }
    with pytest.raises(InvalidPlanError):
        await service.apply(AlgorithmPlanApply.model_validate(plan), uuid.uuid7())
    assert transaction.commits == 0


async def test_solution_change_resets_template_validation() -> None:
    service, _, _ = make_service()
    problems, _ = await service.apply(
        AlgorithmPlanApply.model_validate(problem_plan()), uuid.uuid7()
    )
    problems[0].templates[0].validated_at = datetime(2026, 1, 1, tzinfo=UTC)
    changed = problem_plan()
    changed["problems"][0]["templates"][0]["solution_code"] = "print(3)"

    await service.apply(AlgorithmPlanApply.model_validate(changed), uuid.uuid7())

    assert problems[0].templates[0].validated_at is None
