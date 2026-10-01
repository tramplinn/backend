from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query

from tramplin.api.dependencies import TeacherUser
from tramplin.api.schemas.algorithm_plans import (
    AlgorithmPlanApply,
    AlgorithmPlanApplyOut,
    AlgorithmPlanPreviewOut,
    TemplateValidationOut,
)
from tramplin.api.schemas.plans import plan_report_fields
from tramplin.core.errors import AppError
from tramplin.services.algorithm_plans import UNVALIDATED_WARNING, AlgorithmPlanService
from tramplin.services.algorithms import AlgorithmAuthoringService

router = APIRouter(
    prefix="/algorithm-plans", tags=["authoring:algorithm-plans"], route_class=DishkaRoute
)


@router.post(
    "/preview",
    summary="Предпросмотр плана банка задач",
    description=(
        "Валидирует план и прогоняет его применение без сохранения: возвращает точный diff "
        "и найденные проблемы. Эталонные решения не запускаются."
    ),
)
async def preview_algorithm_plan(
    payload: AlgorithmPlanApply,
    user: TeacherUser,
    plans: FromDishka[AlgorithmPlanService],
) -> AlgorithmPlanPreviewOut:
    report = await plans.preview(payload, user.id)
    return AlgorithmPlanPreviewOut.model_validate(plan_report_fields(report))


@router.post(
    "/apply",
    summary="Применить план банка задач",
    description=(
        "Массово создаёт или обновляет алгоритмические задачи (тесты, шаблоны решений) из "
        "одного документа; используется MCP-сервером для программного наполнения банка задач. "
        "С validate_templates=true после сохранения прогоняет эталонные решения плана по "
        "тест-кейсам; провал проверки не откатывает сохранённый план."
    ),
)
async def apply_algorithm_plan(
    payload: AlgorithmPlanApply,
    user: TeacherUser,
    plans: FromDishka[AlgorithmPlanService],
    authoring: FromDishka[AlgorithmAuthoringService],
    validate_templates: bool = Query(default=False),
) -> AlgorithmPlanApplyOut:
    problems, report = await plans.apply(payload, user.id)
    validations: list[TemplateValidationOut] = []
    if validate_templates:
        report.warnings = [item for item in report.warnings if item != UNVALIDATED_WARNING]
        for problem, problem_plan in zip(problems, payload.problems, strict=True):
            for template in problem_plan.templates:
                if not template.solution_code.strip():
                    continue
                try:
                    await authoring.validate_template(problem.id, template.language, user.id)
                # Любой отказ (решение не прошло, раннер недоступен) — результат проверки,
                # а не ошибка запроса: план к этому моменту уже сохранён.
                except AppError as error:
                    validations.append(
                        TemplateValidationOut(
                            problem_slug=problem.slug,
                            language=template.language,
                            passed=False,
                            message=error.message,
                            details=error.details,
                        )
                    )
                else:
                    validations.append(
                        TemplateValidationOut(
                            problem_slug=problem.slug, language=template.language, passed=True
                        )
                    )
    return AlgorithmPlanApplyOut.model_validate(
        {**plan_report_fields(report), "template_validations": validations}
    )
