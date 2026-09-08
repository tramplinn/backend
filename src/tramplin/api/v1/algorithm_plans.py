from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter

from tramplin.api.dependencies import TeacherUser
from tramplin.api.schemas.algorithm_plans import AlgorithmPlanApply, AlgorithmPlanApplyOut
from tramplin.services.algorithm_plans import AlgorithmPlanService

router = APIRouter(
    prefix="/algorithm-plans", tags=["authoring:algorithm-plans"], route_class=DishkaRoute
)


@router.post(
    "/apply",
    summary="Применить план банка задач",
    description=(
        "Массово создаёт или обновляет алгоритмические задачи (тесты, шаблоны решений) из "
        "одного документа; используется MCP-сервером для программного наполнения банка задач."
    ),
)
async def apply_algorithm_plan(
    payload: AlgorithmPlanApply,
    user: TeacherUser,
    plans: FromDishka[AlgorithmPlanService],
) -> AlgorithmPlanApplyOut:
    _, stats = await plans.apply(payload, user.id)
    return AlgorithmPlanApplyOut(
        created=stats.created,
        updated=stats.updated,
        unchanged=stats.unchanged,
    )
