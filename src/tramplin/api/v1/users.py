from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query

from tramplin.api.dependencies import CurrentUser
from tramplin.api.project_mapping import project_card_out
from tramplin.api.schemas.pagination import PageOut
from tramplin.api.schemas.users import CourseActivityOut, PublicProfileOut, PublicUserOut
from tramplin.api.user_mapping import with_resume_url
from tramplin.core.config import Settings
from tramplin.models.enums import ProfileBlock
from tramplin.services.profile_layout import ProfileLayoutService
from tramplin.services.projects import ProjectService
from tramplin.services.users import UserService

router = APIRouter(prefix="/users", tags=["users"], route_class=DishkaRoute)
SearchQuery = Annotated[str | None, Query(max_length=200)]


@router.get(
    "",
    summary="Поиск пользователей",
    description="Поиск по активным пользователям с постраничным выводом; только для вошедших.",
)
async def search_users(
    _: CurrentUser,
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
    summary="Профиль пользователя",
    description=(
        "Профиль по логину, только для вошедших: видимые блоки в порядке, выбранном "
        "пользователем, и только те проекты, которые доступны текущему зрителю."
    ),
)
async def get_user_profile(
    login: str,
    viewer: CurrentUser,
    users: FromDishka[UserService],
    layouts: FromDishka[ProfileLayoutService],
    projects: FromDishka[ProjectService],
    settings: FromDishka[Settings],
) -> PublicProfileOut:
    user, stats, courses = await users.get_public_profile(login)
    layout = await layouts.visible_blocks(user.id)
    shown = set(layout)
    show_stats = ProfileBlock.STATS in shown
    project_views = (
        await projects.list_for_profile(user, viewer) if ProfileBlock.PROJECTS in shown else []
    )
    base_url = settings.s3_public_base_url
    public = PublicUserOut.model_validate(user).model_dump()
    if ProfileBlock.ABOUT not in shown:
        public["interests"] = []
    profile = PublicProfileOut(
        **public,
        bio=user.bio if ProfileBlock.ABOUT in shown else None,
        completed_lessons=stats.completed_lessons if show_stats else None,
        passed_quizzes=stats.passed_quizzes if show_stats else None,
        solved_algorithms=stats.solved_algorithms if show_stats else None,
        active_courses=(
            [CourseActivityOut.model_validate(course) for course in courses]
            if ProfileBlock.COURSES in shown
            else []
        ),
        layout=layout,
        projects=[project_card_out(view, asset_base_url=base_url) for view in project_views],
    )
    if ProfileBlock.RESUME not in shown:
        return profile
    return with_resume_url(profile, user, asset_base_url=base_url)
