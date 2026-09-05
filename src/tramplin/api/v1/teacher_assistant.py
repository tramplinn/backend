from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter

from tramplin.api.dependencies import TeacherUser
from tramplin.api.schemas.teacher_assistant import TeacherAssistantIn, TeacherAssistantOut
from tramplin.services.teacher_assistant import TeacherAssistantService

router = APIRouter(prefix="/assistant", route_class=DishkaRoute)


@router.post("/suggest")
async def suggest(
    payload: TeacherAssistantIn,
    _: TeacherUser,
    assistant: FromDishka[TeacherAssistantService],
) -> TeacherAssistantOut:
    result = await assistant.suggest(
        payload.surface,
        payload.instruction,
        payload.document.to_document(),
    )
    return TeacherAssistantOut.model_validate(result)
