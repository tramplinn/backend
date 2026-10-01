from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter

from tramplin.api.dependencies import TeacherUser
from tramplin.api.schemas.course_plans import (
    CoursePlanApply,
    CoursePlanApplyOut,
    CoursePlanPreviewOut,
    PracticeSetPlanApply,
    PracticeSetPlanOut,
)
from tramplin.api.schemas.plans import plan_report_fields
from tramplin.services.course_plans import CoursePlanService

router = APIRouter(prefix="/course-plans", tags=["authoring:course-plans"], route_class=DishkaRoute)


@router.post(
    "/preview",
    summary="Предпросмотр плана курса",
    description=(
        "Валидирует план и прогоняет его применение без сохранения: возвращает точный diff "
        "(тот же код, что и apply) и найденные проблемы. При ошибках diff не строится."
    ),
)
async def preview_course_plan(
    payload: CoursePlanApply,
    user: TeacherUser,
    plans: FromDishka[CoursePlanService],
) -> CoursePlanPreviewOut:
    report = await plans.preview(payload, user.id)
    return CoursePlanPreviewOut.model_validate(
        {"course_slug": payload.slug, **plan_report_fields(report)}
    )


@router.post(
    "/apply",
    summary="Применить план курса",
    description=(
        "Массово создаёт или обновляет структуру курса (модули, уроки, тесты, наборы практики) "
        "из одного документа; используется MCP-сервером для программного наполнения курсов. "
        "План с ошибками отклоняется с кодом invalid_plan и списком details.issues."
    ),
)
async def apply_course_plan(
    payload: CoursePlanApply,
    user: TeacherUser,
    plans: FromDishka[CoursePlanService],
) -> CoursePlanApplyOut:
    course, report = await plans.apply(payload, user.id)
    return CoursePlanApplyOut.model_validate(
        {"course_id": course.id, "course_slug": course.slug, **plan_report_fields(report)}
    )


@router.post(
    "/practice-set/preview",
    summary="Предпросмотр одного набора практики",
    description="Как /preview, но для одного набора практики в существующем модуле.",
)
async def preview_practice_set_plan(
    payload: PracticeSetPlanApply,
    user: TeacherUser,
    plans: FromDishka[CoursePlanService],
) -> PracticeSetPlanOut:
    report = await plans.preview_practice_set(
        payload.course_slug, payload.module_slug, payload.practice_set, user.id
    )
    return PracticeSetPlanOut.model_validate(
        {
            "course_slug": payload.course_slug,
            "module_slug": payload.module_slug,
            **plan_report_fields(report),
        }
    )


@router.post(
    "/practice-set/apply",
    summary="Применить один набор практики",
    description=(
        "Создаёт или обновляет набор практики (matching по title) в существующем модуле. "
        "Не меняет остальные элементы модуля, их порядок и статусы курса/модуля."
    ),
)
async def apply_practice_set_plan(
    payload: PracticeSetPlanApply,
    user: TeacherUser,
    plans: FromDishka[CoursePlanService],
) -> PracticeSetPlanOut:
    report = await plans.apply_practice_set(
        payload.course_slug, payload.module_slug, payload.practice_set, user.id
    )
    return PracticeSetPlanOut.model_validate(
        {
            "course_slug": payload.course_slug,
            "module_slug": payload.module_slug,
            **plan_report_fields(report),
        }
    )
