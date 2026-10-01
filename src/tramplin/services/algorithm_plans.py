from __future__ import annotations

from collections import Counter

import uuid_utils.compat as uuid

from tramplin.models.algorithms import AlgorithmProblem, AlgorithmTemplate, AlgorithmTestCase
from tramplin.models.enums import AlgorithmProvider, ContentStatus
from tramplin.services.algorithm_plan_schemas import (
    AlgorithmPlanApply,
    ProblemPlan,
    TemplatePlan,
    TestCasePlan,
)
from tramplin.services.algorithm_ports import AlgorithmAuthoringRepositoryPort
from tramplin.services.contracts import Transaction
from tramplin.services.lesson_markdown import render_markdown
from tramplin.services.plan_report import PlanReport
from tramplin.services.tags import TagRepositoryPort

ADDITIVE_WARNING = "Additive-only: тест-кейсы и шаблоны существующей задачи вне плана сохраняются."
UNVALIDATED_WARNING = (
    "Эталонные решения не прогоняются по тестам, пока apply не вызван с validate_templates=true."
)


class AlgorithmPlanService:
    """Применяет план банка задач одной транзакцией; ошибка откатывает план целиком.

    Задачи — плоский список, matching по slug (как курсы в CoursePlanService).
    Тест-кейсы matching по position, шаблоны — по language (уже natural key).
    Additive-only: элементы вне плана внутри существующей задачи не удаляются.
    preview прогоняет тот же код без commit.
    """

    def __init__(
        self,
        transaction: Transaction,
        algorithms: AlgorithmAuthoringRepositoryPort,
        tags: TagRepositoryPort,
    ) -> None:
        self._transaction = transaction
        self._algorithms = algorithms
        self._tags = tags

    def validate(self, plan: AlgorithmPlanApply) -> PlanReport:
        report = PlanReport()
        slugs = Counter(problem.slug for problem in plan.problems)
        for slug, count in slugs.items():
            if count > 1:
                report.error(slug, "duplicate_problem", "slug задачи повторяется в плане")
        for problem in plan.problems:
            self._validate_problem(problem, report)
        return report

    async def preview(self, plan: AlgorithmPlanApply, actor_id: uuid.UUID) -> PlanReport:
        report = self.validate(plan)
        if report.valid:
            await self._apply(plan, actor_id, report)
            await self._transaction.flush()
        return report

    async def apply(
        self, plan: AlgorithmPlanApply, actor_id: uuid.UUID
    ) -> tuple[list[AlgorithmProblem], PlanReport]:
        report = self.validate(plan)
        report.raise_if_invalid()
        problems = await self._apply(plan, actor_id, report)
        await self._transaction.commit()
        return problems, report

    @staticmethod
    def _validate_problem(problem: ProblemPlan, report: PlanReport) -> None:
        path = problem.slug
        if problem.provider == AlgorithmProvider.INTERNAL and not problem.statement_md.strip():
            report.warning(path, "empty_statement", "Пустое условие")
        if problem.provider == AlgorithmProvider.EXTERNAL and problem.external_url is None:
            report.error(path, "missing_external_url", "external_url обязателен для внешней задачи")
        if problem.external_url is not None and problem.external_url.scheme != "https":
            report.error(path, "insecure_external_url", "external_url должен быть HTTPS")
        if not problem.test_cases:
            report.warning(path, "no_test_cases", "Нет тест-кейсов")
        elif not any(case.is_sample for case in problem.test_cases):
            report.warning(path, "no_sample_test", "Нет ни одного sample-теста")
        positions = Counter(case.position for case in problem.test_cases)
        for position, count in positions.items():
            if count > 1:
                report.error(
                    f"{path}/test-cases/{position}",
                    "duplicate_test_case_position",
                    "position тест-кейса должен быть уникальным внутри задачи",
                )
        languages = Counter(template.language for template in problem.templates)
        for language, count in languages.items():
            if count > 1:
                report.error(
                    f"{path}/templates/{language}",
                    "duplicate_template_language",
                    "Шаблон для языка указан дважды",
                )
        for template in problem.templates:
            if not template.solution_code.strip():
                report.warning(
                    f"{path}/templates/{template.language}",
                    "missing_solution",
                    "Нет эталонного решения: шаблон нельзя будет провалидировать",
                )

    async def _apply(
        self, plan: AlgorithmPlanApply, actor_id: uuid.UUID, report: PlanReport
    ) -> list[AlgorithmProblem]:
        problems: list[AlgorithmProblem] = []
        for problem_plan in plan.problems:
            path = problem_plan.slug
            external_url = str(problem_plan.external_url) if problem_plan.external_url else None
            problem = await self._algorithms.get_problem_by_slug(problem_plan.slug)
            if problem is None:
                problem = AlgorithmProblem(
                    slug=problem_plan.slug,
                    provider=problem_plan.provider,
                    external_key=problem_plan.external_key,
                    external_url=external_url,
                    title=problem_plan.title,
                    statement_md=problem_plan.statement_md,
                    statement_html=render_markdown(problem_plan.statement_md),
                    difficulty=problem_plan.difficulty,
                    time_limit_ms=problem_plan.time_limit_ms,
                    memory_limit_kb=problem_plan.memory_limit_kb,
                    status=ContentStatus.DRAFT,
                )
                problem.test_cases, problem.templates = [], []
                problem.tags = await self._tags.get_or_create_many(problem_plan.tags)
                report.create("problem", path, problem, actor_id)
                self._algorithms.add_problem(problem)
            else:
                report.warnings.append(ADDITIVE_WARNING)
                change = report.update(
                    "problem",
                    path,
                    problem,
                    {
                        "provider": problem_plan.provider,
                        "external_key": problem_plan.external_key,
                        "external_url": external_url,
                        "title": problem_plan.title,
                        "statement_md": problem_plan.statement_md,
                        "difficulty": problem_plan.difficulty,
                        "time_limit_ms": problem_plan.time_limit_ms,
                        "memory_limit_kb": problem_plan.memory_limit_kb,
                    },
                    actor_id,
                )
                if "statement_md" in change.fields:
                    problem.statement_html = render_markdown(problem_plan.statement_md)
                if await self._sync_tags(problem, problem_plan.tags):
                    change.touch("tags")
            self._apply_test_cases(problem, path, problem_plan.test_cases, actor_id, report)
            self._apply_templates(problem, path, problem_plan.templates, actor_id, report)
            problems.append(problem)
        if plan.problems:
            report.warnings.append(UNVALIDATED_WARNING)
        return problems

    async def _sync_tags(self, problem: AlgorithmProblem, tag_names: list[str]) -> bool:
        if sorted(tag_names) == sorted(tag.name for tag in problem.tags):
            return False
        problem.tags = await self._tags.get_or_create_many(tag_names)
        return True

    def _apply_test_cases(
        self,
        problem: AlgorithmProblem,
        path: str,
        plans: list[TestCasePlan],
        actor_id: uuid.UUID,
        report: PlanReport,
    ) -> None:
        existing = {case.position: case for case in problem.test_cases}
        any_case_changed = False
        for case_plan in plans:
            case_path = f"{path}/test-cases/{case_plan.position}"
            values: dict[str, object] = {
                "input": case_plan.input,
                "expected_output": case_plan.expected_output,
                "is_sample": case_plan.is_sample,
                "weight": case_plan.weight,
            }
            case = existing.get(case_plan.position)
            if case is None:
                case = AlgorithmTestCase(
                    problem_id=problem.id, position=case_plan.position, **values
                )
                report.create("test_case", case_path, case, actor_id)
                self._algorithms.add_test_case(case)
                problem.test_cases.append(case)
                any_case_changed = True
            else:
                change = report.update("test_case", case_path, case, values, actor_id)
                any_case_changed = any_case_changed or change.action == "update"
        if any_case_changed:
            for template in problem.templates:
                template.validated_at = None

    def _apply_templates(
        self,
        problem: AlgorithmProblem,
        path: str,
        plans: list[TemplatePlan],
        actor_id: uuid.UUID,
        report: PlanReport,
    ) -> None:
        existing = {template.language: template for template in problem.templates}
        for template_plan in plans:
            template_path = f"{path}/templates/{template_plan.language}"
            values: dict[str, object] = {
                "starter_code": template_plan.starter_code,
                "solution_code": template_plan.solution_code,
            }
            template = existing.get(template_plan.language)
            if template is None:
                template = AlgorithmTemplate(
                    problem_id=problem.id, language=template_plan.language, **values
                )
                report.create("template", template_path, template, actor_id)
                self._algorithms.add_template(template)
                problem.templates.append(template)
            else:
                change = report.update("template", template_path, template, values, actor_id)
                if "solution_code" in change.fields:
                    template.validated_at = None
