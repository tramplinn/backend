from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query

from tramplin.api.content_mapping import news_out
from tramplin.api.schemas.news import NewsOut
from tramplin.api.schemas.pagination import PageOut
from tramplin.core.config import Settings
from tramplin.services.news import NewsService

router = APIRouter(prefix="/news", tags=["news"], route_class=DishkaRoute)


@router.get("")
async def list_news(
    news: FromDishka[NewsService],
    settings: FromDishka[Settings],
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
) -> PageOut[NewsOut]:
    """Лента главной. Открыта без входа: новости — витрина, а не учебный материал."""
    page = await news.list(limit=limit, offset=offset)
    return PageOut(
        items=[news_out(item, asset_base_url=settings.s3_public_base_url) for item in page.items],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{slug}")
async def get_news(
    slug: str,
    news: FromDishka[NewsService],
    settings: FromDishka[Settings],
) -> NewsOut:
    return news_out(await news.get(slug), asset_base_url=settings.s3_public_base_url)
