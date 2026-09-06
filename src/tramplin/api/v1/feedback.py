from typing import Annotated

import uuid_utils.compat as uuid
from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query, status

from tramplin.api.content_mapping import asset_out
from tramplin.api.dependencies import AdminUser, CurrentUser
from tramplin.api.schemas.feedback import FeedbackCreate, FeedbackOut, FeedbackStatusUpdate
from tramplin.api.schemas.pagination import PageOut
from tramplin.core.config import Settings
from tramplin.models.enums import FeedbackStatus
from tramplin.models.feedback import Feedback
from tramplin.services.feedback import FeedbackService

router = APIRouter(prefix="/feedback", tags=["feedback"], route_class=DishkaRoute)
admin_router = APIRouter(prefix="/admin/feedback", tags=["admin"], route_class=DishkaRoute)
FeedbackStatusFilter = Annotated[FeedbackStatus | None, Query(alias="status")]


def _feedback_out(feedback: Feedback, *, asset_base_url: str) -> FeedbackOut:
    return FeedbackOut(
        id=feedback.id,
        author_id=feedback.author_id,
        message=feedback.message,
        page_path=feedback.page_path,
        status=feedback.status,
        attachments=[
            asset_out(attachment.asset, asset_base_url=asset_base_url)
            for attachment in feedback.attachments
        ],
        created_at=feedback.created_at,
        updated_at=feedback.updated_at,
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Отправить обратную связь",
    description="Создаёт обращение пользователя со ссылкой на страницу и вложениями.",
)
async def submit_feedback(
    payload: FeedbackCreate,
    user: CurrentUser,
    feedback: FromDishka[FeedbackService],
    settings: FromDishka[Settings],
) -> FeedbackOut:
    created = await feedback.submit(
        payload.message,
        user.id,
        page_path=payload.page_path,
        attachment_ids=payload.attachment_ids,
    )
    return _feedback_out(created, asset_base_url=settings.s3_public_base_url)


@admin_router.get(
    "",
    summary="Список обращений (админ)",
    description="Обращения с фильтром по статусу, постранично.",
)
async def list_feedback(
    _: AdminUser,
    feedback: FromDishka[FeedbackService],
    settings: FromDishka[Settings],
    status_filter: FeedbackStatusFilter = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> PageOut[FeedbackOut]:
    page = await feedback.list(status=status_filter, limit=limit, offset=offset)
    return PageOut(
        items=[
            _feedback_out(item, asset_base_url=settings.s3_public_base_url) for item in page.items
        ],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


@admin_router.patch(
    "/{feedback_id}",
    summary="Изменить статус обращения (админ)",
    description="Переводит обращение в новый статус обработки.",
)
async def update_feedback_status(
    feedback_id: uuid.UUID,
    payload: FeedbackStatusUpdate,
    admin: AdminUser,
    feedback: FromDishka[FeedbackService],
    settings: FromDishka[Settings],
) -> FeedbackOut:
    updated = await feedback.set_status(feedback_id, payload.status, admin.id)
    return _feedback_out(updated, asset_base_url=settings.s3_public_base_url)


@admin_router.delete(
    "/{feedback_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить обращение (админ)",
    description="Безвозвратно удаляет обращение вместе с вложениями.",
)
async def delete_feedback(
    feedback_id: uuid.UUID,
    _: AdminUser,
    feedback: FromDishka[FeedbackService],
) -> None:
    await feedback.delete(feedback_id)
