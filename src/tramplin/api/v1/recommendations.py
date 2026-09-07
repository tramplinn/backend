from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter

from tramplin.api.dependencies import OptionalUser
from tramplin.api.recommendation_mapping import recommended_algorithm_out, recommended_course_out
from tramplin.api.schemas.recommendations import RecommendationsOut
from tramplin.services.recommendations import RecommendationService

router = APIRouter(prefix="/recommendations", tags=["recommendations"], route_class=DishkaRoute)


@router.get(
    "",
    summary="Персональные рекомендации",
    description=(
        "Курсы и алгоритмические задачи, подобранные под прогресс текущего "
        "пользователя; для гостя возвращает общую подборку."
    ),
)
async def list_recommendations(
    user: OptionalUser,
    service: FromDishka[RecommendationService],
) -> RecommendationsOut:
    recommendations = await service.list_for(user)
    return RecommendationsOut(
        courses=[recommended_course_out(course) for course in recommendations.courses],
        algorithms=[recommended_algorithm_out(problem) for problem in recommendations.algorithms],
    )
