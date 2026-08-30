import uuid_utils.compat as uuid
from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, status

from tramplin.api.content_mapping import lesson_out
from tramplin.api.dependencies import TeacherUser
from tramplin.api.schemas.lessons import (
    InterviewCardPreviewOut,
    LessonCreate,
    LessonOut,
    LessonUpdate,
    MarkdownPreviewIn,
    MarkdownPreviewOut,
)
from tramplin.models.content import Lesson
from tramplin.services.lessons import LessonService

router = APIRouter(route_class=DishkaRoute)


@router.post("/markdown/preview")
async def preview_markdown(
    payload: MarkdownPreviewIn,
    _: TeacherUser,
    lessons: FromDishka[LessonService],
) -> MarkdownPreviewOut:
    rendered = await lessons.preview(payload.body_md)
    return MarkdownPreviewOut(
        body_html=rendered.body_html,
        interview_cards=[
            InterviewCardPreviewOut.model_validate(card) for card in rendered.interview_cards
        ],
    )


@router.post("/modules/{module_id}/lessons", status_code=status.HTTP_201_CREATED)
async def create_lesson(
    module_id: uuid.UUID,
    payload: LessonCreate,
    user: TeacherUser,
    lessons: FromDishka[LessonService],
) -> LessonOut:
    lesson = Lesson(module_id=module_id, **payload.model_dump())
    return lesson_out(await lessons.create(module_id, lesson, user.id))


@router.get("/lessons/{lesson_id}")
async def get_lesson(
    lesson_id: uuid.UUID,
    _: TeacherUser,
    lessons: FromDishka[LessonService],
) -> LessonOut:
    """Черновики видны только здесь: публичный роут отдаёт лишь опубликованное."""
    return lesson_out(await lessons.get(lesson_id, published_only=False))


@router.patch("/lessons/{lesson_id}")
async def update_lesson(
    lesson_id: uuid.UUID,
    payload: LessonUpdate,
    user: TeacherUser,
    lessons: FromDishka[LessonService],
) -> LessonOut:
    lesson = await lessons.update(lesson_id, payload.model_dump(exclude_unset=True), user.id)
    return lesson_out(lesson)


@router.delete("/lessons/{lesson_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lesson(
    lesson_id: uuid.UUID,
    _: TeacherUser,
    lessons: FromDishka[LessonService],
) -> None:
    await lessons.delete(lesson_id)
