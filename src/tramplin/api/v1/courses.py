import uuid_utils.compat as uuid
from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query, status

from tramplin.api.content_mapping import course_out, course_tree_out
from tramplin.api.dependencies import TeacherUser
from tramplin.api.schemas.courses import (
    CourseCreate,
    CourseOut,
    CourseTreeOut,
    CourseUpdate,
)
from tramplin.api.schemas.pagination import PageOut
from tramplin.api.schemas.publish_cascade import PublishReportOut
from tramplin.core.config import Settings
from tramplin.models.content import Course
from tramplin.services.courses import CourseService
from tramplin.services.publish_cascade import PublishCascadeService

router = APIRouter(prefix="/courses", tags=["authoring:courses"], route_class=DishkaRoute)


@router.get(
    "",
    summary="Список курсов (автор)",
    description="Все курсы, включая черновики, для авторской панели.",
)
async def list_courses(
    _: TeacherUser,
    courses: FromDishka[CourseService],
    settings: FromDishka[Settings],
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
) -> PageOut[CourseOut]:
    page = await courses.list(published_only=False, limit=limit, offset=offset)
    return PageOut(
        items=[
            course_out(course, asset_base_url=settings.s3_public_base_url) for course in page.items
        ],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get(
    "/{slug}",
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
    "",
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
    "/{course_id}",
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
    "/{course_id}",
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


@router.post(
    "/{course_id}/publish",
    summary="Опубликовать всё содержимое курса",
    description=(
        "Публикует курс и всё, что в нём проходит валидацию (модули, уроки, тесты, "
        "наборы практики); что не проходит — пропускает с причиной. Уже опубликованное "
        "не трогает и публикацию не снимает."
    ),
)
async def publish_course_cascade(
    course_id: uuid.UUID,
    user: TeacherUser,
    publish: FromDishka[PublishCascadeService],
) -> PublishReportOut:
    return PublishReportOut.model_validate(await publish.publish_course(course_id, user.id))
