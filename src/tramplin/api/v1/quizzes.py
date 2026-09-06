import uuid_utils.compat as uuid
from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, status

from tramplin.api.content_mapping import question_out, quiz_author_out, quiz_out
from tramplin.api.dependencies import TeacherUser
from tramplin.api.schemas.quizzes import (
    QuizAuthorOut,
    QuizCreate,
    QuizOut,
    QuizQuestionCreate,
    QuizQuestionOut,
    QuizQuestionUpdate,
    QuizUpdate,
)
from tramplin.core.config import Settings
from tramplin.models.quizzes import Quiz, QuizQuestion
from tramplin.services.quizzes import QuizService

router = APIRouter(tags=["authoring:quizzes"], route_class=DishkaRoute)


@router.post("/modules/{module_id}/quizzes", status_code=status.HTTP_201_CREATED)
async def create_quiz(
    module_id: uuid.UUID,
    payload: QuizCreate,
    user: TeacherUser,
    quizzes: FromDishka[QuizService],
    settings: FromDishka[Settings],
) -> QuizOut:
    quiz = Quiz(module_id=module_id, **payload.model_dump())
    return quiz_out(
        await quizzes.create(module_id, quiz, user.id),
        asset_base_url=settings.s3_public_base_url,
    )


@router.patch("/quizzes/{quiz_id}")
async def update_quiz(
    quiz_id: uuid.UUID,
    payload: QuizUpdate,
    user: TeacherUser,
    quizzes: FromDishka[QuizService],
    settings: FromDishka[Settings],
) -> QuizOut:
    quiz = await quizzes.update(quiz_id, payload.model_dump(exclude_unset=True), user.id)
    return quiz_out(quiz, asset_base_url=settings.s3_public_base_url)


@router.get("/quizzes/{quiz_id}")
async def get_quiz(
    quiz_id: uuid.UUID,
    _: TeacherUser,
    quizzes: FromDishka[QuizService],
    settings: FromDishka[Settings],
) -> QuizAuthorOut:
    return quiz_author_out(
        await quizzes.get(quiz_id, published_only=False),
        asset_base_url=settings.s3_public_base_url,
    )


@router.delete("/quizzes/{quiz_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_quiz(
    quiz_id: uuid.UUID,
    _: TeacherUser,
    quizzes: FromDishka[QuizService],
) -> None:
    await quizzes.delete(quiz_id)


@router.post("/quizzes/{quiz_id}/questions", status_code=status.HTTP_201_CREATED)
async def create_question(
    quiz_id: uuid.UUID,
    payload: QuizQuestionCreate,
    user: TeacherUser,
    quizzes: FromDishka[QuizService],
    settings: FromDishka[Settings],
) -> QuizQuestionOut:
    data = payload.model_dump()
    attachment_ids = data.pop("attachment_ids")
    question = QuizQuestion(
        quiz_id=quiz_id,
        options_json=data.pop("options"),
        answer_json=data.pop("answer"),
        **data,
    )
    return question_out(
        await quizzes.create_question(quiz_id, question, user.id, attachment_ids),
        asset_base_url=settings.s3_public_base_url,
    )


@router.patch("/questions/{question_id}")
async def update_question(
    question_id: uuid.UUID,
    payload: QuizQuestionUpdate,
    user: TeacherUser,
    quizzes: FromDishka[QuizService],
    settings: FromDishka[Settings],
) -> QuizQuestionOut:
    changes = payload.model_dump(exclude_unset=True)
    if "options" in changes:
        changes["options_json"] = changes.pop("options")
    if "answer" in changes:
        changes["answer_json"] = changes.pop("answer")
    return question_out(
        await quizzes.update_question(question_id, changes, user.id),
        asset_base_url=settings.s3_public_base_url,
    )


@router.delete("/questions/{question_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_question(
    question_id: uuid.UUID,
    _: TeacherUser,
    quizzes: FromDishka[QuizService],
) -> None:
    await quizzes.delete_question(question_id)
