import httpx

from tests.integration.conftest import Actor
from tests.integration.helpers import assert_error, create
from tests.integration.test_people import upload


async def test_news_lifecycle(client: httpx.AsyncClient, teacher: Actor) -> None:
    h = teacher.headers
    photo = await upload(client, teacher)
    news = await create(
        client,
        "/authoring/news",
        {
            "title": "Запуск",
            "slug": "launch",
            "body_md": "Мы **запустились**",
            "photo_ids": [photo],
        },
        h,
    )
    assert news["status"] == "draft"
    assert news["published_at"] is None
    assert [item["id"] for item in news["photos"]] == [photo]

    assert (await client.get("/authoring/news", headers=h)).json()["total"] == 1
    assert (await client.get(f"/authoring/news/{news['id']}", headers=h)).json()["slug"] == "launch"
    assert (await client.get("/news")).json()["total"] == 0
    assert_error(await client.get("/news/launch"), 404, "not_found")

    published = await client.patch(
        f"/authoring/news/{news['id']}", json={"status": "published", "photo_ids": []}, headers=h
    )
    assert published.status_code == 200, published.text
    assert published.json()["published_at"] is not None
    assert published.json()["photos"] == []

    feed = await client.get("/news")
    assert [item["slug"] for item in feed.json()["items"]] == ["launch"]
    assert (await client.get("/news/launch")).json()["title"] == "Запуск"

    assert (await client.delete(f"/authoring/news/{news['id']}", headers=h)).status_code == 204
    assert_error(await client.get(f"/authoring/news/{news['id']}", headers=h), 404, "not_found")


async def test_news_rejects_duplicate_photos(client: httpx.AsyncClient, teacher: Actor) -> None:
    photo = await upload(client, teacher)

    response = await client.post(
        "/authoring/news",
        json={"title": "Дубли", "slug": "dupes", "photo_ids": [photo, photo]},
        headers=teacher.headers,
    )

    assert_error(response, 422, "validation_error")
