import uuid_utils.compat as uuid
from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query

from tramplin.api.content_mapping import (
    course_out,
    course_tree_out,
    lesson_out,
    quiz_out,
    track_out,
)
from tramplin.api.schemas.courses import CourseOut, CourseTreeOut
from tramplin.api.schemas.lessons import InterviewCardOut, LessonOut
from tramplin.api.schemas.modules import ModuleDependencyOut
from tramplin.api.schemas.pagination import PageOut
from tramplin.api.schemas.quizzes import QuizOut
from tramplin.api.schemas.tracks import TrackOut
from tramplin.core.config import Settings
from tramplin.services.courses import CourseService
from tramplin.services.lessons import LessonService
from tramplin.services.modules import ModuleService
from tramplin.services.quizzes import QuizService
from tramplin.services.tracks import TrackService

router = APIRouter(tags=["content"], route_class=DishkaRoute)


@router.get(
    "/tracks",
    summary="Список треков",
    description="Публичный каталог опубликованных треков.",
)
async def list_tracks(
    tracks: FromDishka[TrackService],
    settings: FromDishka[Settings],
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
) -> PageOut[TrackOut]:
    page = await tracks.list(limit=limit, offset=offset)
    return PageOut(
        items=[
            track_out(track, published_only=True, asset_base_url=settings.s3_public_base_url)
            for track in page.items
        ],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get(
    "/tracks/{slug}",
    summary="Трек по slug",
    description="Публичная карточка трека со списком его опубликованных курсов.",
)
async def get_track(
    slug: str,
    tracks: FromDishka[TrackService],
    settings: FromDishka[Settings],
) -> TrackOut:
    return track_out(
        await tracks.get(slug),
        published_only=True,
        asset_base_url=settings.s3_public_base_url,
    )


@router.get(
    "/courses",
    summary="Список курсов",
    description="Публичный каталог опубликованных курсов.",
)
async def list_courses(
    courses: FromDishka[CourseService],
    settings: FromDishka[Settings],
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
) -> PageOut[CourseOut]:
    page = await courses.list(limit=limit, offset=offset)
    return PageOut(
        items=[
            course_out(course, asset_base_url=settings.s3_public_base_url) for course in page.items
        ],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get(
    "/courses/{slug}",
    summary="Курс по slug",
    description="Публичное дерево курса: только опубликованные модули и уроки.",
)
async def get_course(
    slug: str,
    courses: FromDishka[CourseService],
    settings: FromDishka[Settings],
) -> CourseTreeOut:
    return course_tree_out(
        await courses.get(slug),
        published_only=True,
        asset_base_url=settings.s3_public_base_url,
    )


@router.get(
    "/courses/{slug}/module-dependencies",
    summary="Зависимости модулей курса",
    description="Рёбра графа доступности между опубликованными модулями курса.",
)
async def list_module_dependencies(
    slug: str,
    modules: FromDishka[ModuleService],
) -> list[ModuleDependencyOut]:
    return [
        ModuleDependencyOut.model_validate(dependency)
        for dependency in await modules.list_dependencies(slug)
    ]


@router.get(
    "/lessons/{lesson_id}",
    summary="Урок по id",
    description="Публичный урок; черновики доступны только через authoring-роут.",
)
async def get_lesson(lesson_id: uuid.UUID, lessons: FromDishka[LessonService]) -> LessonOut:
    return lesson_out(await lessons.get(lesson_id))


@router.get(
    "/lessons/{lesson_id}/interview-cards",
    summary="Карточки для собеседований урока",
    description="Вопросы-карточки, извлечённые из содержимого урока.",
)
async def list_interview_cards(
    lesson_id: uuid.UUID,
    lessons: FromDishka[LessonService],
) -> list[InterviewCardOut]:
    return [
        InterviewCardOut.model_validate(card)
        for card in await lessons.list_interview_cards(lesson_id)
    ]


@router.get(
    "/quizzes/{quiz_id}",
    summary="Тест по id",
    description="Публичный тест с вопросами, но без правильных ответов.",
)
async def get_quiz(
    quiz_id: uuid.UUID,
    quizzes: FromDishka[QuizService],
    settings: FromDishka[Settings],
) -> QuizOut:
    return quiz_out(
        await quizzes.get(quiz_id),
        asset_base_url=settings.s3_public_base_url,
    )
