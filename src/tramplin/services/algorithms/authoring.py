from collections.abc import Sequence
from typing import Any

import uuid_utils.compat as uuid

from tramplin.core.config import Settings
from tramplin.core.errors import ConflictError, InvalidAlgorithmProblemError, NotFoundError
from tramplin.core.time import utc_now
from tramplin.models.algorithms import (
    AlgorithmProblem,
    AlgorithmTemplate,
    AlgorithmTestCase,
    PracticeSet,
    PracticeSetProblem,
)
from tramplin.models.enums import AlgorithmProvider, AlgorithmVerdict, ContentStatus, PracticeMode
from tramplin.services.algorithm_execution import execute_and_wait
from tramplin.services.algorithm_ports import (
    AlgorithmAuthoringRepositoryPort,
    AlgorithmModuleRepositoryPort,
)
from tramplin.services.contracts import CodeRunner, PageResult, RunRequest, Transaction
from tramplin.services.entity_updates import (
    apply_order_by,
    mark_created,
    mark_updated,
    require,
    validate_required_updates,
)
from tramplin.services.lesson_markdown import render_markdown
from tramplin.services.modules import next_module_item
from tramplin.services.tags import TagRepositoryPort


class AlgorithmAuthoringService:
    def __init__(
        self,
        transaction: Transaction,
        algorithms: AlgorithmAuthoringRepositoryPort,
        modules: AlgorithmModuleRepositoryPort,
        runner: CodeRunner,
        settings: Settings,
        tags: TagRepositoryPort,
    ) -> None:
        self._transaction = transaction
        self._algorithms = algorithms
        self._modules = modules
        self._runner = runner
        self._settings = settings
        self._tags = tags

    async def get_problem(self, problem_id: uuid.UUID) -> AlgorithmProblem:
        return require(
            await self._algorithms.get_problem(problem_id, published_only=False),
            NotFoundError("Алгоритмическая задача не найдена"),
        )

    async def get_problem_by_slug(self, slug: str) -> AlgorithmProblem | None:
        return await self._algorithms.get_problem_by_slug(slug)

    async def list_problems(
        self, *, limit: int = 20, offset: int = 0
    ) -> PageResult[AlgorithmProblem]:
        items, total = await self._algorithms.list_problems(limit=limit, offset=offset)
        return PageResult(items=items, total=total, limit=limit, offset=offset)

    async def create_problem(
        self, problem: AlgorithmProblem, tag_names: list[str], actor_id: uuid.UUID
    ) -> AlgorithmProblem:
        publishing = problem.status is ContentStatus.PUBLISHED
        _validate_problem_source(problem, require_statement=publishing)
        problem.statement_html = render_markdown(problem.statement_md)
        problem.test_cases, problem.templates = [], []
        problem.tags = await self._tags.get_or_create_many(tag_names)
        mark_created(problem, actor_id)
        self._algorithms.add_problem(problem)
        await self._transaction.commit()
        return problem

    async def update_problem(
        self, problem_id: uuid.UUID, changes: dict[str, Any], actor_id: uuid.UUID
    ) -> AlgorithmProblem:
        problem = await self.get_problem(problem_id)
        if "statement_md" in changes:
            changes["statement_html"] = render_markdown(changes["statement_md"])
        if "tags" in changes:
            problem.tags = await self._tags.get_or_create_many(changes.pop("tags"))
        validate_required_updates(changes, {"slug", "title", "difficulty", "status"})
        was_published = problem.status is ContentStatus.PUBLISHED
        problem.slug = changes.get("slug", problem.slug)
        problem.provider = changes.get("provider", problem.provider)
        problem.external_key = changes.get("external_key", problem.external_key)
        problem.external_url = changes.get("external_url", problem.external_url)
        problem.title = changes.get("title", problem.title)
        problem.statement_md = changes.get("statement_md", problem.statement_md)
        problem.statement_html = changes.get("statement_html", problem.statement_html)
        problem.difficulty = changes.get("difficulty", problem.difficulty)
        problem.time_limit_ms = changes.get("time_limit_ms", problem.time_limit_ms)
        problem.memory_limit_kb = changes.get("memory_limit_kb", problem.memory_limit_kb)
        problem.status = changes.get("status", problem.status)
        # Публикуемость проверяем только при переходе в published — иначе правка уже
        # опубликованной задачи блокируется требованием провалидировать решение.
        publishing = problem.status is ContentStatus.PUBLISHED and not was_published
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
        await self.get_problem(problem_id)
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
