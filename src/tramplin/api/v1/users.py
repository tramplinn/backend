from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query

from tramplin.api.schemas.pagination import PageOut
from tramplin.api.schemas.users import CourseActivityOut, PublicProfileOut, PublicUserOut
from tramplin.api.user_mapping import with_resume_url
from tramplin.core.config import Settings
from tramplin.services.users import UserService

router = APIRouter(prefix="/users", tags=["users"], route_class=DishkaRoute)
SearchQuery = Annotated[str | None, Query(max_length=200)]


@router.get(
    "",
    summary="Поиск пользователей",
    description="Публичный поиск по активным пользователям с постраничным выводом.",
)
async def search_users(
    users: FromDishka[UserService],
    q: SearchQuery = None,
    limit: int = Query(default=24, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
) -> PageOut[PublicUserOut]:
    page = await users.list(query=q, is_active=True, limit=limit, offset=offset)
    return PageOut(
        items=[PublicUserOut.model_validate(user) for user in page.items],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get(
    "/{login}",
    summary="Публичный профиль пользователя",
    description="Профиль по логину вместе со сводной статистикой обучения.",
)
async def get_user_profile(
    login: str,
    users: FromDishka[UserService],
    settings: FromDishka[Settings],
) -> PublicProfileOut:
    user, stats, courses = await users.get_public_profile(login)
    profile = PublicProfileOut(
        **PublicUserOut.model_validate(user).model_dump(),
        bio=user.bio,
        completed_lessons=stats.completed_lessons,
        passed_quizzes=stats.passed_quizzes,
        solved_algorithms=stats.solved_algorithms,
        active_courses=[CourseActivityOut.model_validate(course) for course in courses],
    )
    return with_resume_url(profile, user, asset_base_url=settings.s3_public_base_url)
