"""ИИ-функции: репетитор (SSE), ассистент автора и рекомендации. LLM — фейк."""

import json
from typing import Any

import httpx
import pytest

from tests.integration.conftest import Actor
from tests.integration.fakes import Fakes
from tests.integration.helpers import assert_error, problem, published_course

GUEST_COOKIE = "tramplin_guest"
QUESTION = {"messages": [{"role": "user", "content": "Зачем нужна хэш-функция?"}]}


def sse_events(response: httpx.Response) -> list[dict[str, Any]]:
    return [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]


async def test_tutor_streams_answer_about_lesson(
    client: httpx.AsyncClient, teacher: Actor, student: Actor, fakes: Fakes
) -> None:
    content = await published_course(client, teacher.headers)

    response = await client.post(
        f"/tutor/lessons/{content['lesson']['id']}/messages", json=QUESTION, headers=student.headers
    )

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    assert sse_events(response) == [
        {"delta": "Подсказка: "},
        {"delta": "подумайте о хэше."},
        {"done": True},
    ]
    assert "Хэш-таблицы" in fakes.llm.prompts[-1].system
    assert GUEST_COOKIE not in response.cookies


async def test_tutor_streams_answer_about_problem_to_guest(
    client: httpx.AsyncClient, teacher: Actor, fakes: Fakes
) -> None:
    created = await problem(client, teacher.headers)

    response = await client.post(
        f"/tutor/algorithm-problems/{created['id']}/messages", json=QUESTION
    )

    assert response.status_code == 200, response.text
    assert sse_events(response)[-1] == {"done": True}
    assert "A + B" in fakes.llm.prompts[-1].system
    assert response.cookies.get(GUEST_COOKIE)


async def test_tutor_guest_quota(client: httpx.AsyncClient, teacher: Actor) -> None:
    content = await published_course(client, teacher.headers)
    path = f"/tutor/lessons/{content['lesson']['id']}/messages"

    # Гостевая кука сохраняется в клиенте — квота считается на одного гостя.
    for _ in range(3):
        assert (await client.post(path, json=QUESTION)).status_code == 200

    assert_error(await client.post(path, json=QUESTION), 429, "too_many_requests")


async def test_tutor_requires_question_last(
    client: httpx.AsyncClient, teacher: Actor, student: Actor
) -> None:
    content = await published_course(client, teacher.headers)

    response = await client.post(
        f"/tutor/lessons/{content['lesson']['id']}/messages",
        json={"messages": [{"role": "assistant", "content": "Чем помочь?"}]},
        headers=student.headers,
    )

    assert_error(response, 422, "unprocessable")


async def test_tutor_unknown_lesson(client: httpx.AsyncClient, student: Actor) -> None:
    response = await client.post(
        f"/tutor/lessons/{student.id}/messages", json=QUESTION, headers=student.headers
    )

    assert_error(response, 404, "not_found")


async def test_teacher_assistant_suggests_patch(
    client: httpx.AsyncClient, teacher: Actor, fakes: Fakes
) -> None:
    response = await client.post(
        "/authoring/assistant/suggest",
        json={
            "surface": "lesson",
            "instruction": "Сократи вступление",
            "document": {"title": "Хэши", "body_md": "# Очень длинное вступление"},
        },
        headers=teacher.headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["explanation"] == "Сократил вступление."
    assert response.json()["body_md"] == "# Кратко"
    assert "Сократи вступление" in json.dumps(
        [turn.content for turn in fakes.llm.prompts[-1].turns], ensure_ascii=False
    )


async def test_teacher_assistant_forbidden_for_student(
    client: httpx.AsyncClient, student: Actor
) -> None:
    response = await client.post(
        "/authoring/assistant/suggest",
        json={"surface": "lesson", "instruction": "x", "document": {"title": "t"}},
        headers=student.headers,
    )

    assert_error(response, 403, "forbidden")


async def test_recommendations_for_guest_are_empty(client: httpx.AsyncClient) -> None:
    response = await client.get("/recommendations")

    assert response.status_code == 200
    assert response.json() == {"courses": [], "algorithms": []}


async def test_recommendations_for_student(
    client: httpx.AsyncClient, teacher: Actor, student: Actor
) -> None:
    await published_course(client, teacher.headers)
    created = await problem(client, teacher.headers)

    response = await client.get("/recommendations", headers=student.headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert [course["slug"] for course in body["courses"]] == ["algo"]
    assert [item["id"] for item in body["algorithms"]] == [created["id"]]


@pytest.mark.parametrize("surface", ["lesson", "algorithm_problem"])
async def test_teacher_assistant_validates_payload(
    client: httpx.AsyncClient, teacher: Actor, surface: str
) -> None:
    response = await client.post(
        "/authoring/assistant/suggest",
        json={"surface": surface, "instruction": "", "document": {"title": "t"}},
        headers=teacher.headers,
    )

    assert_error(response, 422, "validation_error")
