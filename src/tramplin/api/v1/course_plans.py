from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter

from tramplin.api.dependencies import TeacherUser
from tramplin.api.schemas.course_plans import CoursePlanApply, CoursePlanApplyOut
from tramplin.services.course_plans import CoursePlanService

router = APIRouter(route_class=DishkaRoute)


@router.post("/course-plans/apply")
async def apply_course_plan(
    payload: CoursePlanApply,
    user: TeacherUser,
    plans: FromDishka[CoursePlanService],
) -> CoursePlanApplyOut:
    course, stats = await plans.apply(payload, user.id)
    return CoursePlanApplyOut(
        course_id=course.id,
        course_slug=course.slug,
        created=stats.created,
        updated=stats.updated,
        unchanged=stats.unchanged,
    )
