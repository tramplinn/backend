"""Authoring контента (треки, курсы, модули, уроки, тесты, теги) и публичный каталог."""

from typing import Any

import httpx

from tests.integration.conftest import Actor
from tests.integration.helpers import assert_error, create, published_course


async def test_track_lifecycle(client: httpx.AsyncClient, teacher: Actor) -> None:
    h = teacher.headers
    track = await create(client, "/authoring/tracks", {"title": "Backend", "slug": "backend"}, h)
    first = await create(client, "/authoring/courses", {"title": "Python", "slug": "python"}, h)
    second = await create(client, "/authoring/courses", {"title": "SQL", "slug": "sql"}, h)

    for course in (first, second):
        attach = await client.put(
            f"/authoring/tracks/{track['id']}/courses/{course['id']}", headers=h
        )
        assert attach.status_code == 204, attach.text
    reorder = await client.put(
        f"/authoring/tracks/{track['id']}/courses/order",
        json={"course_ids": [second["id"], first["id"]]},
        headers=h,
    )
    assert reorder.status_code == 204, reorder.text

    detail = await client.get("/authoring/tracks/backend", headers=h)
    assert [item["course"]["slug"] for item in detail.json()["courses"]] == ["sql", "python"]

    updated = await client.patch(
        f"/authoring/tracks/{track['id']}", json={"color": "#ff0000"}, headers=h
    )
    assert updated.json()["color"] == "#ff0000"

    listing = await client.get("/authoring/tracks", headers=h)
    assert listing.json()["total"] == 1

    # Черновик не виден публично, после каскадной публикации — виден вместе с курсами.
    assert_error(await client.get("/tracks/backend"), 404, "not_found")
    report = await client.post(f"/authoring/tracks/{track['id']}/publish", headers=h)
    assert report.status_code == 200, report.text
    assert set(report.json()["published"]) >= {track["id"], first["id"], second["id"]}

    public = await client.get("/tracks/backend")
    assert public.status_code == 200
    assert len(public.json()["courses"]) == 2
    assert (await client.get("/tracks")).json()["total"] == 1

    detach = await client.delete(
        f"/authoring/tracks/{track['id']}/courses/{first['id']}", headers=h
    )
    assert detach.status_code == 204
    assert len((await client.get("/tracks/backend")).json()["courses"]) == 1

    assert (await client.delete(f"/authoring/tracks/{track['id']}", headers=h)).status_code == 204
    assert_error(await client.get("/authoring/tracks/backend", headers=h), 404, "not_found")


async def test_duplicate_slug_is_conflict(client: httpx.AsyncClient, teacher: Actor) -> None:
    await create(client, "/authoring/courses", {"title": "Go", "slug": "go"}, teacher.headers)

    response = await client.post(
        "/authoring/courses", json={"title": "Go 2", "slug": "go"}, headers=teacher.headers
    )

    assert_error(response, 409, "conflict")


async def test_authoring_forbidden_for_student(client: httpx.AsyncClient, student: Actor) -> None:
    response = await client.post(
        "/authoring/tracks", json={"title": "X", "slug": "x"}, headers=student.headers
    )

    assert_error(response, 403, "forbidden")


async def test_authoring_requires_auth(client: httpx.AsyncClient) -> None:
    assert (await client.get("/authoring/courses")).status_code == 401


async def test_course_module_lesson_authoring(client: httpx.AsyncClient, teacher: Actor) -> None:
    h = teacher.headers
    course = await create(
        client, "/authoring/courses", {"title": "Сети", "slug": "net", "tags": ["tcp", "http"]}, h
    )
    intro = await create(
        client,
        f"/authoring/courses/{course['id']}/modules",
        {"title": "Введение", "slug": "intro", "position": 0},
        h,
    )
    deep = await create(
        client,
        f"/authoring/courses/{course['id']}/modules",
        {"title": "Глубже", "slug": "deep", "position": 1},
        h,
    )

    reorder = await client.put(
        f"/authoring/courses/{course['id']}/modules/order",
        json={"ids": [deep["id"], intro["id"]]},
        headers=h,
    )
    assert reorder.status_code == 204, reorder.text

    depend = await client.put(
        f"/authoring/modules/{deep['id']}/dependencies/{intro['id']}", headers=h
    )
    assert depend.status_code == 204, depend.text
    deps = await client.get("/authoring/courses/net/module-dependencies", headers=h)
    assert deps.json() == [{"module_id": deep["id"], "depends_on_id": intro["id"]}]
    cycle = await client.put(
        f"/authoring/modules/{intro['id']}/dependencies/{deep['id']}", headers=h
    )
    assert cycle.status_code in {409, 422}, cycle.text
    undepend = await client.delete(
        f"/authoring/modules/{deep['id']}/dependencies/{intro['id']}", headers=h
    )
    assert undepend.status_code == 204
    assert (await client.get("/authoring/courses/net/module-dependencies", headers=h)).json() == []

    first = await create(
        client,
        f"/authoring/modules/{intro['id']}/lessons",
        {"title": "TCP", "slug": "tcp", "body_md": "**жирно**"},
        h,
    )
    second = await create(
        client, f"/authoring/modules/{intro['id']}/lessons", {"title": "UDP", "slug": "udp"}, h
    )
    assert "<strong>жирно</strong>" in first["body_html"]

    # Порядок ленты задаётся id элементов модуля, а не id уроков.
    items = (await client.get(f"/authoring/modules/{intro['id']}", headers=h)).json()["items"]
    item_ids = {item["lesson"]["slug"]: item["id"] for item in items}
    order = await client.put(
        f"/authoring/modules/{intro['id']}/order",
        json={"ids": [item_ids["udp"], item_ids["tcp"]]},
        headers=h,
    )
    assert order.status_code == 204, order.text
    module = await client.get(f"/authoring/modules/{intro['id']}", headers=h)
    assert [item["lesson"]["slug"] for item in module.json()["items"]] == ["udp", "tcp"]

    lesson = await client.patch(
        f"/authoring/lessons/{first['id']}", json={"title": "TCP/IP"}, headers=h
    )
    assert lesson.json()["title"] == "TCP/IP"
    assert (await client.get(f"/authoring/lessons/{first['id']}", headers=h)).json()[
        "title"
    ] == "TCP/IP"
    assert (await client.delete(f"/authoring/lessons/{second['id']}", headers=h)).status_code == 204
    assert_error(
        await client.get(f"/authoring/lessons/{second['id']}", headers=h), 404, "not_found"
    )

    renamed = await client.patch(
        f"/authoring/modules/{intro['id']}", json={"summary": "Основы"}, headers=h
    )
    assert renamed.json()["summary"] == "Основы"

    patched = await client.patch(
        f"/authoring/courses/{course['id']}", json={"tags": ["tcp"], "est_hours": 3}, headers=h
    )
    assert [tag["name"] for tag in patched.json()["tags"]] == ["tcp"]
    assert patched.json()["est_hours"] == 3

    tags = await client.get("/authoring/tags", headers=h)
    assert {tag["name"] for tag in tags.json()} >= {"tcp"}

    tree = await client.get("/authoring/courses/net", headers=h)
    assert [m["slug"] for m in tree.json()["modules"]] == ["deep", "intro"]
    assert (await client.get("/authoring/courses", headers=h)).json()["total"] == 1

    report = await client.post(f"/authoring/modules/{intro['id']}/publish", headers=h)
    assert report.status_code == 200, report.text
    assert intro["id"] in report.json()["published"]

    assert (await client.delete(f"/authoring/modules/{deep['id']}", headers=h)).status_code == 204
    assert (await client.delete(f"/authoring/courses/{course['id']}", headers=h)).status_code == 204
    assert_error(await client.get("/authoring/courses/net", headers=h), 404, "not_found")


async def test_markdown_preview(client: httpx.AsyncClient, teacher: Actor) -> None:
    response = await client.post(
        "/authoring/markdown/preview",
        json={"body_md": "# Заголовок\n\n:::interview\nВопрос\n---\nОтвет\n:::\n"},
        headers=teacher.headers,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert "<h1" in body["body_html"]
    assert body["interview_cards"] == [
        {"position": 0, "question_md": "Вопрос", "answer_md": "Ответ"}
    ]


async def test_quiz_authoring(client: httpx.AsyncClient, teacher: Actor) -> None:
    h = teacher.headers
    content = await published_course(client, h)
    quiz: dict[str, Any] = content["quiz"]

    question = await create(
        client,
        f"/authoring/quizzes/{quiz['id']}/questions",
        {
            "position": 1,
            "prompt_md": "Выберите хэш-функции",
            "type": "multiple",
            "options": ["sha256", "rot13", "md5"],
            "answer": {"values": ["sha256", "md5"]},
        },
        h,
    )
    updated = await client.patch(
        f"/authoring/questions/{question['id']}", json={"explain_md": "rot13 — шифр"}, headers=h
    )
    assert updated.status_code == 200, updated.text
    assert "answer" not in updated.json()

    published_empty = await client.post(
        f"/authoring/modules/{content['module']['id']}/quizzes",
        json={"title": "Пустой", "slug": "empty", "status": "published"},
        headers=h,
    )
    assert_error(published_empty, 422, "invalid_quiz")

    renamed = await client.patch(
        f"/authoring/quizzes/{quiz['id']}", json={"title": "Итог"}, headers=h
    )
    assert renamed.json()["title"] == "Итог"

    detail = await client.get(f"/authoring/quizzes/{quiz['id']}", headers=h)
    assert detail.json()["questions"][1]["explain_md"] == "rot13 — шифр"
    assert [q["answer"] for q in detail.json()["questions"]] == [
        {"value": "O(1)"},
        {"values": ["sha256", "md5"]},
    ]

    assert (
        await client.delete(f"/authoring/questions/{question['id']}", headers=h)
    ).status_code == 204
    assert (
        len((await client.get(f"/authoring/quizzes/{quiz['id']}", headers=h)).json()["questions"])
        == 1
    )
    assert (await client.delete(f"/authoring/quizzes/{quiz['id']}", headers=h)).status_code == 204
    assert_error(await client.get(f"/authoring/quizzes/{quiz['id']}", headers=h), 404, "not_found")


async def test_public_catalog(client: httpx.AsyncClient, teacher: Actor) -> None:
    content = await published_course(client, teacher.headers)
    await create(
        client, "/authoring/courses", {"title": "Черновик", "slug": "draft"}, teacher.headers
    )

    courses = await client.get("/courses")
    assert [course["slug"] for course in courses.json()["items"]] == ["algo"]
    assert_error(await client.get("/courses/draft"), 404, "not_found")

    tree = await client.get("/courses/algo")
    assert tree.status_code == 200
    kinds = [item["kind"] for item in tree.json()["modules"][0]["items"]]
    assert sorted(kinds) == ["lesson", "quiz"]
    assert (await client.get("/courses/algo/module-dependencies")).json() == []

    cards = await client.get(f"/lessons/{content['lesson']['id']}/interview-cards")
    assert [card["question_md"] for card in cards.json()] == ["Что такое коллизия?"]

    quiz = await client.get(f"/quizzes/{content['quiz']['id']}")
    assert quiz.status_code == 200
    question = quiz.json()["questions"][0]
    # Студент не должен видеть правильный ответ.
    assert "answer" not in question
    assert "explain_md" not in question
