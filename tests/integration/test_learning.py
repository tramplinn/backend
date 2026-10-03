"""Прогресс студента: уроки, курсы, попытки тестов."""

from typing import Any

import httpx

from tests.integration.conftest import Actor
from tests.integration.helpers import assert_error, create, published_course
from tests.integration.test_people import upload


async def test_lesson_and_course_progress(
    client: httpx.AsyncClient, teacher: Actor, student: Actor
) -> None:
    content = await published_course(client, teacher.headers)
    lesson_id = content["lesson"]["id"]

    empty = await client.get("/courses/algo/progress", headers=student.headers)
    assert empty.status_code == 200
    assert (empty.json()["completed_lessons"], empty.json()["total_lessons"]) == (0, 1)

    done = await client.put(f"/progress/lessons/{lesson_id}", headers=student.headers)
    assert done.status_code == 200, done.text
    assert done.json()["lesson_id"] == lesson_id
    # Повторная отметка идемпотентна.
    assert (
        await client.put(f"/progress/lessons/{lesson_id}", headers=student.headers)
    ).status_code == 200

    progress = await client.get("/courses/algo/progress", headers=student.headers)
    assert progress.json()["completed_lessons"] == 1
    assert progress.json()["modules"][0]["completed_lessons"] == 1
    lessons = await client.get("/progress/lessons", headers=student.headers)
    assert [item["lesson_id"] for item in lessons.json()] == [lesson_id]

    reopened = await client.delete(f"/progress/lessons/{lesson_id}", headers=student.headers)
    assert reopened.status_code == 204
    assert (await client.get("/progress/lessons", headers=student.headers)).json() == []

    profile = await client.get(f"/users/{student.login}", headers=student.headers)
    assert profile.json()["completed_lessons"] == 0


async def test_progress_on_draft_lesson_is_not_found(
    client: httpx.AsyncClient, teacher: Actor, student: Actor
) -> None:
    course = await create(
        client, "/authoring/courses", {"title": "Черновик", "slug": "wip"}, teacher.headers
    )
    module = await create(
        client,
        f"/authoring/courses/{course['id']}/modules",
        {"title": "M", "slug": "m", "position": 0},
        teacher.headers,
    )
    lesson = await create(
        client,
        f"/authoring/modules/{module['id']}/lessons",
        {"title": "L", "slug": "l"},
        teacher.headers,
    )

    response = await client.put(f"/progress/lessons/{lesson['id']}", headers=student.headers)

    assert_error(response, 404, "not_found")


async def test_progress_requires_auth(client: httpx.AsyncClient) -> None:
    assert (await client.get("/progress/lessons")).status_code == 401


async def _quiz_with_all_question_types(
    client: httpx.AsyncClient, teacher: Actor
) -> tuple[dict[str, Any], dict[str, str]]:
    content = await published_course(client, teacher.headers)
    quiz_id = content["quiz"]["id"]
    questions: list[dict[str, Any]] = [
        {"type": "text", "options": [], "answer": {"accepted": ["Хэш"]}},
        {"type": "multiple", "options": ["a", "b", "c"], "answer": {"values": ["a", "c"]}},
        {"type": "file", "options": [], "answer": {}},
    ]
    ids = {"single": content["question"]["id"]}
    for position, question in enumerate(questions, start=1):
        created = await create(
            client,
            f"/authoring/quizzes/{quiz_id}/questions",
            {"position": position, "prompt_md": question["type"], **question},
            teacher.headers,
        )
        ids[question["type"]] = created["id"]
    return content, ids


async def test_quiz_attempts(client: httpx.AsyncClient, teacher: Actor, student: Actor) -> None:
    content, ids = await _quiz_with_all_question_types(client, teacher)
    quiz_id = content["quiz"]["id"]
    asset_id = await upload(client, student)

    wrong = await client.post(
        f"/quizzes/{quiz_id}/attempts",
        json={
            "answers": {
                ids["single"]: "O(n)",
                ids["text"]: "нет",
                ids["multiple"]: ["a"],
                ids["file"]: {"asset_id": asset_id},
            }
        },
        headers=student.headers,
    )
    assert wrong.status_code == 201, wrong.text
    results = {item["question_id"]: item["correct"] for item in wrong.json()["results"]}
    assert results[ids["single"]] is False
    assert results[ids["text"]] is False

    right = await client.post(
        f"/quizzes/{quiz_id}/attempts",
        json={
            "answers": {
                ids["single"]: "O(1)",
                ids["text"]: "хэш",
                ids["multiple"]: ["c", "a"],
                ids["file"]: {"asset_id": asset_id},
            }
        },
        headers=student.headers,
    )
    assert right.status_code == 201, right.text
    assert right.json()["score"] > wrong.json()["score"]

    attempts = await client.get(f"/quizzes/{quiz_id}/attempts", headers=student.headers)
    assert len(attempts.json()) == 2
    best = await client.get("/progress/quizzes", headers=student.headers)
    assert [(item["quiz_id"], item["score"]) for item in best.json()] == [
        (quiz_id, right.json()["score"])
    ]


async def test_quiz_attempt_rejects_foreign_file(
    client: httpx.AsyncClient, teacher: Actor, student: Actor
) -> None:
    content, ids = await _quiz_with_all_question_types(client, teacher)
    foreign = await upload(client, teacher)

    response = await client.post(
        f"/quizzes/{content['quiz']['id']}/attempts",
        json={"answers": {ids["file"]: {"asset_id": foreign}}},
        headers=student.headers,
    )

    assert_error(response, 422, "invalid_quiz")
