import uuid_utils.compat as uuid
from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, status

from tramplin.api.dependencies import CurrentUser
from tramplin.api.schemas.learning import (
    CourseProgressOut,
    LessonProgressOut,
    QuestionResultOut,
    QuizAttemptCreate,
    QuizAttemptOut,
    QuizProgressOut,
)
from tramplin.services.progress import ProgressService
from tramplin.services.quiz_attempts import QuizAttemptService

router = APIRouter(tags=["learning"], route_class=DishkaRoute)


@router.get("/courses/{slug}/progress")
async def get_course_progress(
    slug: str,
    user: CurrentUser,
    progress: FromDishka[ProgressService],
) -> CourseProgressOut:
    return CourseProgressOut.model_validate(await progress.course(user.id, slug))


@router.get("/progress/lessons")
async def list_lesson_progress(
    user: CurrentUser,
    progress: FromDishka[ProgressService],
) -> list[LessonProgressOut]:
    return [LessonProgressOut.model_validate(item) for item in await progress.lessons(user.id)]


@router.get("/progress/quizzes")
async def list_quiz_progress(
    user: CurrentUser,
    progress: FromDishka[ProgressService],
) -> list[QuizProgressOut]:
    return [QuizProgressOut.model_validate(item) for item in await progress.quizzes(user.id)]


@router.put("/progress/lessons/{lesson_id}")
async def complete_lesson(
    lesson_id: uuid.UUID,
    user: CurrentUser,
    progress: FromDishka[ProgressService],
) -> LessonProgressOut:
    return LessonProgressOut.model_validate(await progress.complete(user.id, lesson_id))


@router.delete("/progress/lessons/{lesson_id}", status_code=status.HTTP_204_NO_CONTENT)
async def reopen_lesson(
    lesson_id: uuid.UUID,
    user: CurrentUser,
    progress: FromDishka[ProgressService],
) -> None:
    await progress.reopen(user.id, lesson_id)


@router.post("/quizzes/{quiz_id}/attempts", status_code=status.HTTP_201_CREATED)
async def submit_quiz(
    quiz_id: uuid.UUID,
    payload: QuizAttemptCreate,
    user: CurrentUser,
    attempts: FromDishka[QuizAttemptService],
) -> QuizAttemptOut:
    result = await attempts.submit(user.id, quiz_id, payload.answers)
    return QuizAttemptOut(
        id=result.attempt.id,
        quiz_id=result.attempt.quiz_id,
        score=result.attempt.score,
        max_score=result.attempt.max_score,
        results=[QuestionResultOut.model_validate(item) for item in result.results],
    )


@router.get("/quizzes/{quiz_id}/attempts")
async def list_quiz_attempts(
    quiz_id: uuid.UUID,
    user: CurrentUser,
    attempts: FromDishka[QuizAttemptService],
) -> list[QuizAttemptOut]:
    return [QuizAttemptOut.model_validate(item) for item in await attempts.list(user.id, quiz_id)]
