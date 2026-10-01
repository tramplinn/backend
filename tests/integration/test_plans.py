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

    assert_error(response, 422, "invalid_plan")
    issues = response.json()["details"]["issues"]
    assert [issue["code"] for issue in issues] == ["unknown_problem"]


async def test_course_plan_validates_content_order(
    client: httpx.AsyncClient, teacher: Actor
) -> None:
    plan = course_plan()
    plan["modules"][0]["content_order"] = ["hash-functions"]

    response = await client.post(
        "/authoring/course-plans/apply", json=plan, headers=teacher.headers
    )

    assert_error(response, 422, "validation_error")


async def test_previews_do_not_write(client: httpx.AsyncClient, teacher: Actor) -> None:
    h = teacher.headers

    algorithms = await client.post(
        "/authoring/algorithm-plans/preview", json=ALGORITHM_PLAN, headers=h
    )
    assert algorithms.status_code == 200, algorithms.text
    assert algorithms.json()["valid"] is True
    assert algorithms.json()["changes"][0]["action"] == "create"
    missing = await client.get("/authoring/algorithms/problems/slug/two-sum", headers=h)
    assert_error(missing, 404, "not_found")

    course = await client.post("/authoring/course-plans/preview", json=course_plan(), headers=h)
    assert course.status_code == 200, course.text
    assert course.json()["valid"] is False
    assert {issue["code"] for issue in course.json()["issues"]} == {"unknown_problem"}
    assert course.json()["changes"] == []

    index = await client.get("/authoring/courses/index", headers=h)
    assert index.json() == {"items": [], "total": 0}


async def test_practice_set_plan_touches_only_its_set(
    client: httpx.AsyncClient, teacher: Actor
) -> None:
    h = teacher.headers
    await client.post("/authoring/algorithm-plans/apply", json=ALGORITHM_PLAN, headers=h)
    await client.post("/authoring/course-plans/apply", json=course_plan(), headers=h)
    payload = {
        "course_slug": "hash-practice",
        "module_slug": "basics",
        "practice_set": {"title": "Добивка", "problem_slugs": ["two-sum"]},
    }

    preview = await client.post(
        "/authoring/course-plans/practice-set/preview", json=payload, headers=h
    )
    assert preview.status_code == 200, preview.text
    assert [(c["action"], c["kind"]) for c in preview.json()["changes"]] == [("create", "practice")]

    applied = await client.post(
        "/authoring/course-plans/practice-set/apply", json=payload, headers=h
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["created"] == 1
    tree = await client.get("/authoring/courses/hash-practice", headers=h)
    items = tree.json()["modules"][0]["items"]
    assert [item["kind"] for item in items] == ["lesson", "practice", "quiz", "practice"]

    missing = await client.post(
        "/authoring/course-plans/practice-set/apply",
        json={**payload, "module_slug": "nope"},
        headers=h,
    )
    assert_error(missing, 404, "not_found")


async def test_track_plan_and_indexes(client: httpx.AsyncClient, teacher: Actor) -> None:
    h = teacher.headers
    await client.post("/authoring/algorithm-plans/apply", json=ALGORITHM_PLAN, headers=h)
    await client.post("/authoring/course-plans/apply", json=course_plan(), headers=h)
    plan = {"title": "Backend", "slug": "backend", "course_slugs": ["hash-practice"]}

    preview = await client.post("/authoring/track-plans/preview", json=plan, headers=h)
    assert preview.status_code == 200, preview.text
    assert preview.json()["created"] == 2

    applied = await client.post("/authoring/track-plans/apply", json=plan, headers=h)
    assert applied.status_code == 200, applied.text
    assert applied.json()["track_slug"] == "backend"
    again = await client.post("/authoring/track-plans/apply", json=plan, headers=h)
    assert (again.json()["created"], again.json()["updated"]) == (0, 0)

    unknown = await client.post(
        "/authoring/track-plans/apply", json={**plan, "course_slugs": ["nope"]}, headers=h
    )
    assert_error(unknown, 422, "invalid_plan")

    tracks = await client.get("/authoring/tracks/index", headers=h)
    assert [item["slug"] for item in tracks.json()["items"]] == ["backend"]
    courses = await client.get("/authoring/courses/index", headers=h)
    assert courses.json()["items"][0]["status"] == "draft"
    problems = await client.get("/authoring/algorithms/problems/index", headers=h)
    assert problems.json()["items"][0]["difficulty"] == "easy"


async def test_algorithm_plan_can_validate_templates(
    client: httpx.AsyncClient, teacher: Actor
) -> None:
    response = await client.post(
        "/authoring/algorithm-plans/apply",
        params={"validate_templates": True},
        json=ALGORITHM_PLAN,
        headers=teacher.headers,
    )

    assert response.status_code == 200, response.text
    validations = response.json()["template_validations"]
    assert [(item["problem_slug"], item["language"]) for item in validations] == [
        ("two-sum", "python")
    ]


async def test_plans_forbidden_for_student(client: httpx.AsyncClient, student: Actor) -> None:
    response = await client.post(
        "/authoring/algorithm-plans/apply", json=ALGORITHM_PLAN, headers=student.headers
    )

    assert_error(response, 403, "forbidden")
