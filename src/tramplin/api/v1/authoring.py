"""Объединяет authoring-маршруты, разделённые по доменным областям."""

from fastapi import APIRouter

from tramplin.api.v1 import (
    algorithm_authoring,
    course_plans,
    courses,
    lessons,
    modules,
    news_authoring,
    quizzes,
    tags_authoring,
    teacher_assistant,
    tracks,
)

router = APIRouter(prefix="/authoring")
router.include_router(tracks.router)
router.include_router(courses.router)
router.include_router(modules.router)
router.include_router(lessons.router)
router.include_router(quizzes.router)
router.include_router(news_authoring.router)
router.include_router(algorithm_authoring.router)
router.include_router(course_plans.router)
router.include_router(teacher_assistant.router)
router.include_router(tags_authoring.router)

__all__ = ["router"]
