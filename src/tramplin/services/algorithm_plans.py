from __future__ import annotations

import uuid_utils.compat as uuid

from tramplin.api.schemas.algorithm_plans import AlgorithmPlanApply, TemplatePlan, TestCasePlan
from tramplin.models.algorithms import AlgorithmProblem, AlgorithmTemplate, AlgorithmTestCase
from tramplin.models.enums import ContentStatus
from tramplin.services.algorithm_ports import AlgorithmAuthoringRepositoryPort
from tramplin.services.contracts import Transaction
from tramplin.services.course_plans import ApplyStats
from tramplin.services.entity_updates import mark_created, mark_updated
from tramplin.services.lesson_markdown import render_markdown
from tramplin.services.tags import TagRepositoryPort


class AlgorithmPlanService:
    """Применяет план банка задач одной транзакцией; ошибка откатывает план целиком.

    Задачи — плоский список, matching по slug (как курсы в CoursePlanService).
    Тест-кейсы matching по position, шаблоны — по language (уже natural key).
    Additive-only: элементы вне плана внутри существующей задачи не удаляются.
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

    async def apply(
        self, plan: AlgorithmPlanApply, actor_id: uuid.UUID
    ) -> tuple[list[AlgorithmProblem], ApplyStats]:
        stats = ApplyStats()
        problems: list[AlgorithmProblem] = []
        for problem_plan in plan.problems:
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
                mark_created(problem, actor_id)
                self._algorithms.add_problem(problem)
                stats.created += 1
            else:
                tags_changed = await self._sync_tags(problem, problem_plan.tags)
                self._update(
                    problem,
                    {
                        "provider": problem_plan.provider,
                        "external_key": problem_plan.external_key,
                        "external_url": external_url,
                        "title": problem_plan.title,
                        "statement_md": problem_plan.statement_md,
                        "statement_html": render_markdown(problem_plan.statement_md),
                        "difficulty": problem_plan.difficulty,
                        "time_limit_ms": problem_plan.time_limit_ms,
                        "memory_limit_kb": problem_plan.memory_limit_kb,
                    },
                    actor_id,
                    stats,
                    force_changed=tags_changed,
                )
            self._apply_test_cases(problem, problem_plan.test_cases, actor_id, stats)
            self._apply_templates(problem, problem_plan.templates, actor_id, stats)
            problems.append(problem)
        await self._transaction.commit()
        return problems, stats

    async def _sync_tags(self, problem: AlgorithmProblem, tag_names: list[str]) -> bool:
        if sorted(tag_names) == sorted(tag.name for tag in problem.tags):
            return False
        problem.tags = await self._tags.get_or_create_many(tag_names)
        return True

    def _apply_test_cases(
        self,
        problem: AlgorithmProblem,
        plans: list[TestCasePlan],
        actor_id: uuid.UUID,
        stats: ApplyStats,
    ) -> None:
        existing = {case.position: case for case in problem.test_cases}
        any_case_changed = False
        for case_plan in plans:
            values = {
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
                mark_created(case, actor_id)
                self._algorithms.add_test_case(case)
                problem.test_cases.append(case)
                stats.created += 1
                any_case_changed = True
            else:
                before = stats.updated
                self._update(case, values, actor_id, stats)
                any_case_changed = any_case_changed or stats.updated > before
        if any_case_changed:
            for template in problem.templates:
                template.validated_at = None

    def _apply_templates(
        self,
        problem: AlgorithmProblem,
        plans: list[TemplatePlan],
        actor_id: uuid.UUID,
        stats: ApplyStats,
    ) -> None:
        existing = {template.language: template for template in problem.templates}
        for template_plan in plans:
            values: dict[str, object] = {
                "starter_code": template_plan.starter_code,
                "solution_code": template_plan.solution_code,
            }
            template = existing.get(template_plan.language)
            if template is None:
                template = AlgorithmTemplate(
                    problem_id=problem.id, language=template_plan.language, **values
                )
                mark_created(template, actor_id)
                self._algorithms.add_template(template)
                problem.templates.append(template)
                stats.created += 1
            else:
                self._update(template, values, actor_id, stats)

    @staticmethod
    def _update(
        entity: AlgorithmProblem | AlgorithmTestCase | AlgorithmTemplate,
        values: dict[str, object],
        actor_id: uuid.UUID,
        stats: ApplyStats,
        *,
        force_changed: bool = False,
    ) -> None:
        changed = force_changed
        for field, value in values.items():
            if getattr(entity, field) != value:
                setattr(entity, field, value)
                changed = True
        if changed:
            mark_updated(entity, actor_id)
            stats.updated += 1
        else:
            stats.unchanged += 1
