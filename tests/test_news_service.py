from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import pytest

from tests.fakes import FakeSession
from tramplin.api.content_mapping import news_out
from tramplin.core.errors import InvalidUpdateError, NotFoundError
from tramplin.models.assets import Asset
from tramplin.models.base import new_id
from tramplin.models.enums import AssetMime, ContentStatus
from tramplin.models.news import News
from tramplin.services.news import NewsService


def dependency(**values: Any) -> Any:
    return cast(Any, SimpleNamespace(**values))


def photo(name: str = "photo.png") -> Asset:
    return Asset(filename=name, s3_key=f"assets/{name}", mime=AssetMime.PNG, size=1)


def service(
    session: FakeSession,
    news_repository: Any,
    assets: Any = None,
) -> NewsService:
    return NewsService(
        session, news_repository, assets or dependency(get=AsyncMock(return_value=None))
    )


async def test_create_orders_photos_by_the_order_they_arrived() -> None:
    first, second = photo("first.png"), photo("second.png")
    assets = {first.id: first, second.id: second}
    session = FakeSession()
    repository = dependency(add=Mock())
    created = await service(
        session,
        repository,
        dependency(get=AsyncMock(side_effect=lambda asset_id: assets.get(asset_id))),
    ).create(
        News(title="Открытие", slug="otkrytie", status=ContentStatus.DRAFT),
        new_id(),
        [second.id, first.id],
    )

    assert [item.asset_id for item in created.photos] == [second.id, first.id]
    assert [item.position for item in created.photos] == [0, 1]
    assert session.commits == 1
    repository.add.assert_called_once()


async def test_publishing_stamps_the_date_once() -> None:
    stamped = datetime(2026, 1, 1, tzinfo=UTC)
    news = News(
        title="Новость",
        slug="novost",
        status=ContentStatus.PUBLISHED,
        published_at=stamped,
    )
    repository = dependency(get=AsyncMock(return_value=news))

    updated = await service(FakeSession(), repository).update(
        news.id, {"title": "Правка"}, new_id()
    )

    assert updated.published_at == stamped


async def test_draft_gets_no_publication_date_until_it_is_published() -> None:
    news = News(title="Черновик", slug="chernovik", body_md="", status=ContentStatus.DRAFT)
    repository = dependency(get=AsyncMock(return_value=news))
    editor = service(FakeSession(), repository)

    assert (await editor.update(news.id, {}, new_id())).published_at is None

    published = await editor.update(news.id, {"status": ContentStatus.PUBLISHED}, new_id())

    assert published.published_at is not None


async def test_repeated_photo_is_rejected() -> None:
    same = photo()
    repository = dependency(add=Mock())

    with pytest.raises(InvalidUpdateError):
        await service(
            FakeSession(), repository, dependency(get=AsyncMock(return_value=same))
        ).create(
            News(title="N", slug="n", body_md="", status=ContentStatus.DRAFT),
            new_id(),
            [same.id, same.id],
        )


async def test_missing_photo_is_reported() -> None:
    with pytest.raises(NotFoundError):
        await service(FakeSession(), dependency(add=Mock())).create(
            News(title="N", slug="n", body_md="", status=ContentStatus.DRAFT), new_id(), [new_id()]
        )


async def test_unknown_news_is_not_found() -> None:
    editor = service(
        FakeSession(),
        dependency(
            get=AsyncMock(return_value=None),
            get_by_slug=AsyncMock(return_value=None),
            delete=AsyncMock(),
        ),
    )

    with pytest.raises(NotFoundError):
        await editor.get("missing")
    with pytest.raises(NotFoundError):
        await editor.update(new_id(), {}, new_id())
    with pytest.raises(NotFoundError):
        await editor.delete(new_id())


async def test_list_and_delete_pass_through() -> None:
    news = News(title="N", slug="n", body_md="", status=ContentStatus.PUBLISHED)
    session = FakeSession()
    repository = dependency(
        list=AsyncMock(return_value=([news], 1)),
        get=AsyncMock(return_value=news),
        get_by_slug=AsyncMock(return_value=news),
        delete=AsyncMock(),
    )
    editor = service(session, repository)

    page = await editor.list(limit=5, offset=0)
    assert page.items == [news]
    assert (page.total, page.limit, page.offset) == (1, 5, 0)
    assert await editor.get("n") is news

    await editor.delete(news.id)
    repository.delete.assert_awaited_once_with(news)
    assert session.commits == 1


async def test_photos_are_replaced_wholesale_on_update() -> None:
    replacement = photo("new.png")
    news = News(title="N", slug="n", body_md="", status=ContentStatus.DRAFT)
    repository = dependency(get=AsyncMock(return_value=news))

    updated = await service(
        FakeSession(), repository, dependency(get=AsyncMock(return_value=replacement))
    ).update(news.id, {"photo_ids": [replacement.id]}, new_id())

    assert [item.asset_id for item in updated.photos] == [replacement.id]


async def test_news_out_exposes_photo_urls_in_order() -> None:
    first, second = photo("a.png"), photo("b.png")
    assets = {first.id: first, second.id: second}
    news = await service(
        FakeSession(),
        dependency(add=Mock()),
        dependency(get=AsyncMock(side_effect=lambda asset_id: assets.get(asset_id))),
    ).create(
        News(title="N", slug="n", body_md="", status=ContentStatus.DRAFT),
        new_id(),
        [second.id, first.id],
    )

    out = news_out(news, asset_base_url="https://cdn.test")

    assert [item.url for item in out.photos] == [
        "https://cdn.test/assets/b.png",
        "https://cdn.test/assets/a.png",
    ]
