import json
import logging
from collections.abc import AsyncIterator

import uuid_utils.compat as uuid
from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from tramplin.api.cookies import GUEST_COOKIE_NAME, set_guest_cookie
from tramplin.api.dependencies import OptionalUser
from tramplin.api.schemas.tutor import TutorAskIn
from tramplin.core.config import Settings
from tramplin.core.errors import AppError
from tramplin.infrastructure.llm import ChatPrompt, ChatTurn, LlmClient
from tramplin.services.tutor import Asker, TutorService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tutor", tags=["tutor"], route_class=DishkaRoute)


def _event(payload: dict[str, str | bool]) -> str:
    """Текст едет внутри JSON: в нём бывают переводы строк."""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _events(client: LlmClient, prompt: ChatPrompt) -> AsyncIterator[str]:
    """После начала потока статус уже ушёл, поэтому ошибка едет событием."""
    try:
        async for delta in client.stream(prompt):
            yield _event({"delta": delta})
    except AppError as error:
        yield _event({"error": error.message})
    except Exception:
        logger.exception("Поток ассистента оборвался")
        yield _event({"error": "Ответ прервался. Попробуйте ещё раз."})
    else:
        yield _event({"done": True})


@router.post("/lessons/{lesson_id}/messages")
async def ask(
    lesson_id: uuid.UUID,
    payload: TutorAskIn,
    request: Request,
    user: OptionalUser,
    tutor: FromDishka[TutorService],
    client: FromDishka[LlmClient],
    settings: FromDishka[Settings],
) -> StreamingResponse:
    guest_id = request.cookies.get(GUEST_COOKIE_NAME) or str(uuid.uuid4())
    asker = Asker(
        guest_id=guest_id,
        user_id=user.id if user else None,
        # X-Forwarded-For не читаем: иначе лимит по адресу обходится заголовком.
        ip=request.client.host if request.client else None,
    )
    # Строго до возврата ответа: когда пойдёт первый кусок, request-скоуп
    # уже закрыт вместе с сессией БД.
    prompt = await tutor.prepare(
        asker,
        lesson_id,
        [ChatTurn(role=item.role, content=item.content) for item in payload.messages],
    )
    response = StreamingResponse(
        _events(client, prompt),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-store",
            # Без этого nginx копит ответ целиком и стриминга не будет.
            "X-Accel-Buffering": "no",
        },
    )
    if user is None:
        set_guest_cookie(response, settings, guest_id)
    return response
