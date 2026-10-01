"""Алгоритмические задачи: authoring, подборки, сессии практики, запуски и отправки.

Отправки исполняет отдельный воркер; здесь он вызывается напрямую поверх той же
Postgres и фейкового раннера — проверяем путь «API → БД → воркер → API» целиком.
"""

from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from tests.integration.conftest import Actor
from tests.integration.fakes import FakeCodeRunner, Fakes
from tests.integration.helpers import SOLUTION, assert_error, create, problem, published_course
from tramplin.core.config import Settings
from tramplin.infrastructure.repositories.algorithms import AlgorithmRepository
from tramplin.services.algorithms import AlgorithmWorkerService


async def run_worker(db: AsyncEngine, runner: FakeCodeRunner, settings: Settings) -> None:
    async with async_sessionmaker(db, expire_on_commit=False)() as session:
        worker = AlgorithmWorkerService(session, AlgorithmRepository(session), runner, settings)
        while await worker.process_next():
            pass


async def test_problem_authoring(client: httpx.AsyncClient, teacher: Actor) -> None:
    h = teacher.headers
    created = await problem(client, teacher.headers)
    problem_id = created["id"]
    assert "<strong>два</strong>" in created["statement_html"]

    case = await create(
        client,
        f"/authoring/algorithms/problems/{problem_id}/test-cases",
        {"position": 2, "input": "5 5", "expected_output": "10"},
        h,
    )
    patched_case = await client.patch(
        f"/authoring/algorithms/test-cases/{case['id']}", json={"weight": 3}, headers=h
    )
    assert patched_case.status_code == 200, patched_case.text
    assert patched_case.json()["weight"] == 3

    by_slug = await client.get("/authoring/algorithms/problems/slug/a-plus-b", headers=h)
    assert len(by_slug.json()["test_cases"]) == 3
    assert (
        await client.delete(f"/authoring/algorithms/test-cases/{case['id']}", headers=h)
    ).status_code == 204
    detail = await client.get(f"/authoring/algorithms/problems/{problem_id}", headers=h)
    assert len(detail.json()["test_cases"]) == 2

    listing = await client.get("/authoring/algorithms/problems", headers=h)
    assert [item["slug"] for item in listing.json()["items"]] == ["a-plus-b"]

    go = await client.put(
        f"/authoring/algorithms/problems/{problem_id}/templates/go",
        json={"language": "go", "starter_code": "package main"},
        headers=h,
    )
    assert go.status_code == 200, go.text
    mismatch = await client.put(
        f"/authoring/algorithms/problems/{problem_id}/templates/go",
        json={"language": "java"},
        headers=h,
    )
    assert_error(mismatch, 409, "conflict")
    no_solution = await client.post(
        f"/authoring/algorithms/problems/{problem_id}/templates/go/validate", headers=h
    )
    assert_error(no_solution, 422, "invalid_algorithm_problem")
    removed = await client.delete(
        f"/authoring/algorithms/problems/{problem_id}/templates/go", headers=h
    )
    assert removed.status_code == 204

    assert (
        await client.delete(f"/authoring/algorithms/problems/{problem_id}", headers=h)
    ).status_code == 204
    assert_error(
        await client.get(f"/authoring/algorithms/problems/{problem_id}", headers=h),
        404,
        "not_found",
    )


async def test_student_solves_problem(
    client: httpx.AsyncClient,
    teacher: Actor,
    student: Actor,
    db: AsyncEngine,
    fakes: Fakes,
    integration_settings: Settings,
) -> None:
    created = await problem(client, teacher.headers)
    problem_id = created["id"]
    h = student.headers

    catalog = await client.get("/algorithms/problems", headers=h)
    assert catalog.status_code == 200, catalog.text
    assert [item["id"] for item in catalog.json()["items"]] == [problem_id]
    statement = await client.get(f"/algorithms/problems/{problem_id}", headers=h)
    assert statement.json()["samples"][0]["input"] == "1 2"
    assert "solution_code" not in statement.json()["templates"][0]
    languages = await client.get("/algorithms/languages", headers=h)
    assert len(languages.json()) == 8

    session = await create(client, "/practice-sessions", {}, h)
    run = await client.post(
        f"/algorithms/problems/{problem_id}/runs",
        json={
            "session_id": session["id"],
            "language": "python",
            "source_code": SOLUTION,
            "custom_input": "2 2",
        },
        headers=h,
    )
    assert run.status_code == 202, run.text
    assert run.json()["kind"] == "run"
    await run_worker(db, fakes.runner, integration_settings)

    wrong = await client.post(
        f"/algorithms/problems/{problem_id}/submissions",
        json={
            "session_id": session["id"],
            "language": "python",
            "source_code": SOLUTION + FakeCodeRunner.FAILING_MARKER,
        },
        headers=h,
    )
    assert wrong.status_code == 202, wrong.text
    async with db.connect() as conn:
        outbox = await conn.execute(text("SELECT count(*) FROM algorithm_job_outbox"))
        assert outbox.scalar() == 2
    await run_worker(db, fakes.runner, integration_settings)
    graded = await client.get(f"/algorithms/submissions/{wrong.json()['id']}", headers=h)
    assert graded.json()["status"] == "finished"
    assert graded.json()["verdict"] == "wrong_answer"
    assert graded.json()["failed_test"] == 1

    right = await client.post(
        f"/algorithms/problems/{problem_id}/submissions",
        json={"session_id": session["id"], "language": "python", "source_code": SOLUTION},
        headers=h,
    )
    await run_worker(db, fakes.runner, integration_settings)
    accepted = await client.get(f"/algorithms/submissions/{right.json()['id']}", headers=h)
    assert accepted.json()["verdict"] == "accepted"

    progress = await client.get(f"/algorithms/problems/{problem_id}/progress", headers=h)
    assert progress.json()["status"] == "solved"
    assert progress.json()["attempts"] == 2
    solutions = await client.get(f"/algorithms/problems/{problem_id}/solutions", headers=h)
    assert [item["source_code"] for item in solutions.json()] == [SOLUTION]

    reflection = await client.put(
        f"/algorithms/problems/{problem_id}/reflection",
        json={"complexity_md": "O(1)", "confidence": 5, "reflection_md": "Легко"},
        headers=h,
    )
    assert reflection.status_code == 200, reflection.text
    assert reflection.json()["confidence"] == 5

    completed = await client.post(
        f"/practice-sessions/{session['id']}/complete", json={"reflection_md": "Готово"}, headers=h
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["status"] == "completed"
    fetched = await client.get(f"/practice-sessions/{session['id']}", headers=h)
    assert fetched.json()["reflection_md"] == "Готово"

    closed = await client.post(
        f"/algorithms/problems/{problem_id}/submissions",
        json={"session_id": session["id"], "language": "python", "source_code": SOLUTION},
        headers=h,
    )
    assert closed.status_code in {409, 422}, closed.text

    profile = await client.get(f"/users/{student.login}")
    assert profile.json()["solved_algorithms"] == 1

    # Задачу с решениями можно удалить: история по ней уходит каскадом.
    removed = await client.delete(
        f"/authoring/algorithms/problems/{problem_id}", headers=teacher.headers
    )
    assert removed.status_code == 204, removed.text
    assert_error(
        await client.get(f"/algorithms/submissions/{right.json()['id']}", headers=h),
        404,
        "not_found",
    )


async def test_foreign_session_and_submission_are_hidden(
    client: httpx.AsyncClient, teacher: Actor, student: Actor, make_user: Any
) -> None:
    created = await problem(client, teacher.headers)
    session = await create(client, "/practice-sessions", {}, student.headers)
    submission = await client.post(
        f"/algorithms/problems/{created['id']}/submissions",
        json={"session_id": session["id"], "language": "python", "source_code": SOLUTION},
        headers=student.headers,
    )
    other = await make_user()

    assert_error(
        await client.get(f"/practice-sessions/{session['id']}", headers=other.headers),
        404,
        "not_found",
    )
    assert_error(
        await client.get(
            f"/algorithms/submissions/{submission.json()['id']}", headers=other.headers
        ),
        404,
        "not_found",
    )


async def test_submission_in_unsupported_language(
    client: httpx.AsyncClient, teacher: Actor, student: Actor
) -> None:
    created = await problem(client, teacher.headers)
    session = await create(client, "/practice-sessions", {}, student.headers)

    response = await client.post(
        f"/algorithms/problems/{created['id']}/submissions",
        json={"session_id": session["id"], "language": "kotlin", "source_code": "fun main() {}"},
        headers=student.headers,
    )

    assert response.status_code in {409, 422}, response.text


async def test_draft_problem_is_hidden_from_students(
    client: httpx.AsyncClient, teacher: Actor, student: Actor
) -> None:
    draft = await create(
        client,
        "/authoring/algorithms/problems",
        {"slug": "secret", "title": "Секрет", "statement_md": "", "difficulty": "hard"},
        teacher.headers,
    )

    assert_error(
        await client.get(f"/algorithms/problems/{draft['id']}", headers=student.headers),
        404,
        "not_found",
    )
    assert (await client.get("/algorithms/problems", headers=student.headers)).json()["total"] == 0


async def test_practice_sets(client: httpx.AsyncClient, teacher: Actor, student: Actor) -> None:
    h = teacher.headers
    content = await published_course(client, h)
    first = await problem(client, teacher.headers, "first")
    second = await problem(client, teacher.headers, "second")

    practice = await create(
        client,
        f"/authoring/modules/{content['module']['id']}/practice-sets",
        {
            "title": "Разминка",
            "description": "Две задачи",
            "mode": "mock_interview",
            "duration_minutes": 45,
        },
        h,
    )
    for item in (first, second):
        added = await client.post(
            f"/authoring/practice-sets/{practice['id']}/problems",
            json={"problem_id": item["id"], "recommended_minutes": 20},
            headers=h,
        )
        assert added.status_code == 201, added.text
    reorder = await client.put(
        f"/authoring/practice-sets/{practice['id']}/problems/order",
        json={"problem_ids": [second["id"], first["id"]]},
        headers=h,
    )
    assert reorder.status_code == 204, reorder.text
    detail = await client.get(f"/authoring/practice-sets/{practice['id']}", headers=h)
    assert [item["problem_id"] for item in detail.json()["problems"]] == [second["id"], first["id"]]

    removed = await client.delete(
        f"/authoring/practice-sets/{practice['id']}/problems/{first['id']}", headers=h
    )
    assert removed.status_code == 204

    assert_error(
        await client.get(f"/practice-sets/{practice['id']}", headers=student.headers),
        404,
        "not_found",
    )
    published = await client.patch(
        f"/authoring/practice-sets/{practice['id']}", json={"status": "published"}, headers=h
    )
    assert published.status_code == 200, published.text

    public = await client.get(f"/practice-sets/{practice['id']}", headers=student.headers)
    assert public.status_code == 200
    assert [item["problem_id"] for item in public.json()["problems"]] == [second["id"]]

    session = await create(client, f"/practice-sets/{practice['id']}/sessions", {}, student.headers)
    assert session["mode"] == "mock_interview"
    assert session["practice_set_id"] == practice["id"]
    assert session["deadline_at"] is not None

    tree = await client.get("/courses/algo")
    kinds = [item["kind"] for item in tree.json()["modules"][0]["items"]]
    assert "practice" in kinds

    in_use = await client.delete(f"/authoring/practice-sets/{practice['id']}", headers=h)
    assert in_use.status_code == 204, in_use.text
    assert_error(
        await client.get(f"/practice-sessions/{session['id']}", headers=student.headers),
        404,
        "not_found",
    )

    spare = await create(
        client,
        f"/authoring/modules/{content['module']['id']}/practice-sets",
        {"title": "Запасной", "mode": "practice"},
        h,
    )
    assert (
        await client.delete(f"/authoring/practice-sets/{spare['id']}", headers=h)
    ).status_code == 204
    assert_error(
        await client.get(f"/authoring/practice-sets/{spare['id']}", headers=h), 404, "not_found"
    )


@pytest.mark.parametrize("path", ["/algorithms/problems", "/algorithms/languages"])
async def test_student_algorithm_endpoints_require_auth(
    client: httpx.AsyncClient, path: str
) -> None:
    assert (await client.get(path)).status_code == 401
