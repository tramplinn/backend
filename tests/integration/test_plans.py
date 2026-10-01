"""Массовое наполнение через планы (их применяет MCP-сервер): идемпотентность и связи."""

from typing import Any

import httpx

from tests.integration.conftest import Actor
from tests.integration.helpers import SOLUTION, assert_error

ALGORITHM_PLAN: dict[str, Any] = {
    "problems": [
        {
            "slug": "two-sum",
            "title": "Две суммы",
            "statement_md": "Найдите пару.",
            "difficulty": "easy",
            "tags": ["hash"],
            "test_cases": [
                {"position": 0, "input": "1 2", "expected_output": "3", "is_sample": True},
                {"position": 1, "input": "2 2", "expected_output": "4"},
            ],
            "templates": [
                {"language": "python", "starter_code": "# код", "solution_code": SOLUTION}
            ],
        }
    ]
}


def course_plan(lesson_body: str = "Текст урока.") -> dict[str, Any]:
    return {
        "title": "Хэши на практике",
        "slug": "hash-practice",
        "est_hours": 4,
        "modules": [
            {
                "title": "Основы",
                "slug": "basics",
                "lessons": [
                    {"title": "Хэш-функции", "slug": "hash-functions", "body_md": lesson_body}
                ],
                "quizzes": [
                    {
                        "title": "Проверка",
                        "slug": "check",
                        "lesson_slug": "hash-functions",
                        "questions": [
                            {
                                "position": 0,
                                "prompt_md": "Сложность поиска?",
                                "type": "single",
                                "options": ["O(1)", "O(n)"],
                                "answer": {"value": "O(1)"},
                            }
                        ],
                    }
                ],
                "practice_sets": [{"title": "Разминка", "problem_slugs": ["two-sum"]}],
                "content_order": ["hash-functions", "Разминка", "check"],
            }
        ],
    }


async def test_algorithm_plan_is_idempotent(client: httpx.AsyncClient, teacher: Actor) -> None:
    first = await client.post(
        "/authoring/algorithm-plans/apply", json=ALGORITHM_PLAN, headers=teacher.headers
    )
    assert first.status_code == 200, first.text
    assert first.json()["created"] > 0
    assert first.json()["updated"] == 0

    again = await client.post(
        "/authoring/algorithm-plans/apply", json=ALGORITHM_PLAN, headers=teacher.headers
    )
    assert again.json()["created"] == 0
    assert again.json()["updated"] == 0

    detail = await client.get(
        "/authoring/algorithms/problems/slug/two-sum", headers=teacher.headers
    )
    assert detail.status_code == 200
    assert len(detail.json()["test_cases"]) == 2
    assert [item["language"] for item in detail.json()["templates"]] == ["python"]


async def test_course_plan_builds_and_updates_course(
    client: httpx.AsyncClient, teacher: Actor
) -> None:
    h = teacher.headers
    await client.post("/authoring/algorithm-plans/apply", json=ALGORITHM_PLAN, headers=h)

    created = await client.post("/authoring/course-plans/apply", json=course_plan(), headers=h)
    assert created.status_code == 200, created.text
    assert created.json()["course_slug"] == "hash-practice"
    assert created.json()["created"] > 0

    tree = await client.get("/authoring/courses/hash-practice", headers=h)
    assert tree.status_code == 200, tree.text
    items = tree.json()["modules"][0]["items"]
    assert [item["kind"] for item in items] == ["lesson", "practice", "quiz"]

    unchanged = await client.post("/authoring/course-plans/apply", json=course_plan(), headers=h)
    assert unchanged.json()["created"] == 0
    assert unchanged.json()["updated"] == 0

    edited = await client.post(
        "/authoring/course-plans/apply", json=course_plan("Новый текст."), headers=h
    )
    assert edited.json()["course_id"] == created.json()["course_id"]
    assert edited.json()["updated"] == 1


async def test_course_plan_with_unknown_problem(client: httpx.AsyncClient, teacher: Actor) -> None:
    response = await client.post(
        "/authoring/course-plans/apply", json=course_plan(), headers=teacher.headers
    )

    assert response.status_code in {404, 422}, response.text


async def test_course_plan_validates_content_order(
    client: httpx.AsyncClient, teacher: Actor
) -> None:
    plan = course_plan()
    plan["modules"][0]["content_order"] = ["hash-functions"]

    response = await client.post(
        "/authoring/course-plans/apply", json=plan, headers=teacher.headers
    )

    assert_error(response, 422, "validation_error")


async def test_plans_forbidden_for_student(client: httpx.AsyncClient, student: Actor) -> None:
    response = await client.post(
        "/authoring/algorithm-plans/apply", json=ALGORITHM_PLAN, headers=student.headers
    )

    assert_error(response, 403, "forbidden")
