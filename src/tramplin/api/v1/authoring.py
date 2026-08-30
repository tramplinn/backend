"""Объединяет authoring-маршруты, разделённые по доменным областям."""

from fastapi import APIRouter

from tramplin.api.v1 import (
    courses,
    lessons,
    modules,
    quizzes,
    tracks,
)

router = APIRouter(prefix="/authoring", tags=["authoring"])
router.include_router(tracks.router)
router.include_router(courses.router)
router.include_router(modules.router)
router.include_router(lessons.router)
router.include_router(quizzes.router)

__all__ = ["router"]
