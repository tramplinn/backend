import uuid_utils.compat as uuid
from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter

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
from tramplin.api.schemas.quizzes import QuizOut
from tramplin.api.schemas.tracks import TrackOut
from tramplin.core.config import Settings
from tramplin.services.courses import CourseService
from tramplin.services.lessons import LessonService
from tramplin.services.modules import ModuleService
from tramplin.services.quizzes import QuizService
from tramplin.services.tracks import TrackService

router = APIRouter(tags=["content"], route_class=DishkaRoute)


@router.get("/tracks")
async def list_tracks(
    tracks: FromDishka[TrackService],
    settings: FromDishka[Settings],
) -> list[TrackOut]:
    return [
        track_out(
            track,
            published_only=True,
            asset_base_url=settings.s3_public_base_url,
        )
        for track in await tracks.list()
    ]


@router.get("/tracks/{slug}")
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


@router.get("/courses")
async def list_courses(
    courses: FromDishka[CourseService],
    settings: FromDishka[Settings],
) -> list[CourseOut]:
    return [
        course_out(course, asset_base_url=settings.s3_public_base_url)
        for course in await courses.list()
    ]


@router.get("/courses/{slug}")
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


@router.get("/courses/{slug}/module-dependencies")
async def list_module_dependencies(
    slug: str,
    modules: FromDishka[ModuleService],
) -> list[ModuleDependencyOut]:
    return [
        ModuleDependencyOut.model_validate(dependency)
        for dependency in await modules.list_dependencies(slug)
    ]


@router.get("/lessons/{lesson_id}")
async def get_lesson(lesson_id: uuid.UUID, lessons: FromDishka[LessonService]) -> LessonOut:
    return lesson_out(await lessons.get(lesson_id))


@router.get("/lessons/{lesson_id}/interview-cards")
async def list_interview_cards(
    lesson_id: uuid.UUID,
    lessons: FromDishka[LessonService],
) -> list[InterviewCardOut]:
    return [
        InterviewCardOut.model_validate(card)
        for card in await lessons.list_interview_cards(lesson_id)
    ]


@router.get("/quizzes/{quiz_id}")
async def get_quiz(
    quiz_id: uuid.UUID,
    quizzes: FromDishka[QuizService],
    settings: FromDishka[Settings],
) -> QuizOut:
    return quiz_out(
        await quizzes.get(quiz_id),
        asset_base_url=settings.s3_public_base_url,
    )
