import uuid_utils.compat as uuid
from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query, status

from tramplin.api.content_mapping import news_out
from tramplin.api.dependencies import TeacherUser
from tramplin.api.schemas.news import NewsCreate, NewsOut, NewsUpdate
from tramplin.api.schemas.pagination import PageOut
from tramplin.core.config import Settings
from tramplin.models.news import News
from tramplin.services.news import NewsService

router = APIRouter(prefix="/news", tags=["authoring:news"], route_class=DishkaRoute)


@router.get(
    "",
    summary="Список новостей автора",
    description="Все новости, включая черновики, для авторской панели.",
)
async def list_drafts(
    _: TeacherUser,
    news: FromDishka[NewsService],
    settings: FromDishka[Settings],
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
) -> PageOut[NewsOut]:
    page = await news.list(published_only=False, limit=limit, offset=offset)
    return PageOut(
        items=[news_out(item, asset_base_url=settings.s3_public_base_url) for item in page.items],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Создать новость",
    description="Создаёт новость как черновик; фото прикрепляются по asset id.",
)
async def create_news(
    payload: NewsCreate,
    user: TeacherUser,
    news: FromDishka[NewsService],
    settings: FromDishka[Settings],
) -> NewsOut:
    data = payload.model_dump()
    photo_ids = data.pop("photo_ids")
    created = await news.create(News(**data), user.id, photo_ids)
    return news_out(created, asset_base_url=settings.s3_public_base_url)


@router.patch(
    "/{news_id}",
    summary="Изменить новость",
    description="Частичное обновление; передаются только изменённые поля.",
)
async def update_news(
    news_id: uuid.UUID,
    payload: NewsUpdate,
    user: TeacherUser,
    news: FromDishka[NewsService],
    settings: FromDishka[Settings],
) -> NewsOut:
    updated = await news.update(news_id, payload.model_dump(exclude_unset=True), user.id)
    return news_out(updated, asset_base_url=settings.s3_public_base_url)


@router.delete(
    "/{news_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить новость",
    description="Безвозвратно удаляет новость.",
)
async def delete_news(
    news_id: uuid.UUID,
    _: TeacherUser,
    news: FromDishka[NewsService],
) -> None:
    await news.delete(news_id)
