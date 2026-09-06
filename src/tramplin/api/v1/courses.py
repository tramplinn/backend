import uuid_utils.compat as uuid
from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, status

from tramplin.api.content_mapping import course_out, course_tree_out
from tramplin.api.dependencies import TeacherUser
from tramplin.api.schemas.courses import (
    CourseCreate,
    CourseOut,
    CourseTreeOut,
    CourseUpdate,
)
from tramplin.core.config import Settings
from tramplin.models.content import Course
from tramplin.services.courses import CourseService

router = APIRouter(tags=["authoring:courses"], route_class=DishkaRoute)


@router.get(
    "/courses",
    summary="Список курсов (автор)",
    description="Все курсы, включая черновики, для авторской панели.",
)
async def list_courses(
    _: TeacherUser,
    courses: FromDishka[CourseService],
    settings: FromDishka[Settings],
) -> list[CourseOut]:
    return [
        course_out(course, asset_base_url=settings.s3_public_base_url)
        for course in await courses.list(published_only=False)
    ]


@router.get(
    "/courses/{slug}",
    summary="Курс по slug (автор)",
    description="Полное дерево курса вместе с черновиками модулей и уроков.",
)
async def get_course(
    slug: str,
    _: TeacherUser,
    courses: FromDishka[CourseService],
    settings: FromDishka[Settings],
) -> CourseTreeOut:
    course = await courses.get(slug, published_only=False)
    return course_tree_out(
        course,
        published_only=False,
        asset_base_url=settings.s3_public_base_url,
    )


@router.post(
    "/courses",
    status_code=status.HTTP_201_CREATED,
    summary="Создать курс",
    description="Создаёт курс как черновик; теги указываются по имени и создаются при отсутствии.",
)
async def create_course(
    payload: CourseCreate,
    user: TeacherUser,
    courses: FromDishka[CourseService],
    settings: FromDishka[Settings],
) -> CourseOut:
    data = payload.model_dump()
    tag_names = data.pop("tags")
    return course_out(
        await courses.create(Course(**data), tag_names, user.id),
        asset_base_url=settings.s3_public_base_url,
    )


@router.patch(
    "/courses/{course_id}",
    summary="Изменить курс",
    description="Частичное обновление; передаются только изменённые поля.",
)
async def update_course(
    course_id: uuid.UUID,
    payload: CourseUpdate,
    user: TeacherUser,
    courses: FromDishka[CourseService],
    settings: FromDishka[Settings],
) -> CourseOut:
    return course_out(
        await courses.update(course_id, payload.model_dump(exclude_unset=True), user.id),
        asset_base_url=settings.s3_public_base_url,
    )


@router.delete(
    "/courses/{course_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить курс",
    description="Безвозвратно удаляет курс вместе с модулями и уроками.",
)
async def delete_course(
    course_id: uuid.UUID,
    _: TeacherUser,
    courses: FromDishka[CourseService],
) -> None:
    await courses.delete(course_id)
