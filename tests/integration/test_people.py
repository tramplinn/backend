"""Пользователи, админка, обратная связь и загрузка файлов."""

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import MissingGreenlet
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.conftest import Actor, MakeUser
from tests.integration.fakes import PUBLIC_BASE_URL, Fakes
from tests.integration.helpers import assert_error
from tramplin.models.enums import UserRole

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


async def upload(client: httpx.AsyncClient, actor: Actor, name: str = "shot.png") -> str:
    response = await client.post(
        "/assets",
        files={"file": (name, PNG, "image/png")},
        data={"mime": "image/png"},
        headers=actor.headers,
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def test_upload_asset_stores_object(
    client: httpx.AsyncClient, fakes: Fakes, student: Actor, db: AsyncEngine
) -> None:
    response = await client.post(
        "/assets",
        files={"file": ("resume.pdf", b"%PDF-1.7 test", "application/pdf")},
        data={"mime": "application/pdf"},
        headers=student.headers,
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["filename"] == "resume.pdf"
    assert body["mime"] == "application/pdf"
    assert body["size"] == len(b"%PDF-1.7 test")
    assert body["url"].startswith(PUBLIC_BASE_URL)
    assert len(fakes.storage.objects) == 1
    async with db.connect() as conn:
        owner = await conn.execute(
            text("SELECT created_by FROM assets WHERE id = :id"), {"id": body["id"]}
        )
        assert owner.scalar() == student.id


async def test_upload_rejects_empty_file(client: httpx.AsyncClient, student: Actor) -> None:
    response = await client.post(
        "/assets",
        files={"file": ("empty.png", b"", "image/png")},
        data={"mime": "image/png"},
        headers=student.headers,
    )

    assert_error(response, 422, "unprocessable")


async def test_upload_requires_auth(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/assets", files={"file": ("a.png", PNG, "image/png")}, data={"mime": "image/png"}
    )

    assert response.status_code == 401


async def test_search_users_and_public_profile(
    client: httpx.AsyncClient, make_user: MakeUser
) -> None:
    alice = await make_user(login="alice-dev")
    await make_user(login="bob-dev")
    await make_user(login="ghost-dev", is_active=False)
    await client.patch("/auth/me", json={"bio": "Пишу на Go"}, headers=alice.headers)

    search = await client.get("/users", params={"q": "alice"})
    assert search.status_code == 200
    page = search.json()
    assert page["total"] == 1
    assert page["items"][0]["login"] == "alice-dev"
    assert "email" not in page["items"][0]

    profile = await client.get("/users/alice-dev")
    assert profile.status_code == 200
    assert profile.json()["bio"] == "Пишу на Go"
    assert profile.json()["completed_lessons"] == 0


async def test_public_profile_not_found(client: httpx.AsyncClient) -> None:
    assert_error(await client.get("/users/nobody"), 404, "not_found")


async def test_admin_lists_and_updates_users(
    client: httpx.AsyncClient, admin: Actor, make_user: MakeUser
) -> None:
    target = await make_user(login="promote-me")

    listing = await client.get("/admin/users", params={"q": "promote"}, headers=admin.headers)
    assert listing.status_code == 200
    assert [item["login"] for item in listing.json()["items"]] == ["promote-me"]

    update = await client.patch(
        f"/admin/users/{target.id}",
        json={"role": "teacher", "is_active": False},
        headers=admin.headers,
    )
    assert update.status_code == 200, update.text
    assert update.json()["role"] == "teacher"
    assert update.json()["is_active"] is False

    # Деактивированный пользователь больше не проходит аутентификацию.
    assert (await client.get("/auth/me", headers=target.headers)).status_code == 403


async def test_admin_updates_name_and_student_number(
    client: httpx.AsyncClient, admin: Actor, student: Actor, make_user: MakeUser
) -> None:
    response = await client.patch(
        f"/admin/users/{student.id}",
        json={"name": "Иван Петров", "student_number": "S-001"},
        headers=admin.headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["name"] == "Иван Петров"
    assert response.json()["student_number"] == "S-001"
    listing = await client.get("/admin/users", params={"q": student.login}, headers=admin.headers)
    assert listing.json()["items"][0]["student_number"] == "S-001"

    cleared = await client.patch(
        f"/admin/users/{student.id}", json={"student_number": None}, headers=admin.headers
    )
    assert cleared.json()["student_number"] is None
    assert cleared.json()["name"] == "Иван Петров"

    other = await make_user()
    await client.patch(
        f"/admin/users/{other.id}", json={"student_number": "S-002"}, headers=admin.headers
    )
    duplicate = await client.patch(
        f"/admin/users/{student.id}", json={"student_number": "S-002"}, headers=admin.headers
    )
    assert_error(duplicate, 409, "conflict")


async def test_admin_cannot_demote_self(client: httpx.AsyncClient, admin: Actor) -> None:
    response = await client.patch(
        f"/admin/users/{admin.id}", json={"role": "student"}, headers=admin.headers
    )

    assert_error(response, 409, "conflict")


async def test_admin_endpoints_forbidden_for_teacher(
    client: httpx.AsyncClient, teacher: Actor
) -> None:
    assert_error(await client.get("/admin/users", headers=teacher.headers), 403, "forbidden")


async def test_code_runner_status(client: httpx.AsyncClient, admin: Actor) -> None:
    health = await client.get("/admin/code-runner/health", headers=admin.headers)
    languages = await client.get("/admin/code-runner/languages", headers=admin.headers)
    queue = await client.get("/admin/code-runner/queue", headers=admin.headers)

    assert health.json() == {"status": "healthy", "languages": 8}
    assert len(languages.json()) == 8
    assert queue.json() == {"queued": 0, "running": 0, "pending_outbox": 0}


async def test_feedback_lifecycle(client: httpx.AsyncClient, student: Actor, admin: Actor) -> None:
    attachment = await upload(client, student)

    created = await client.post(
        "/feedback",
        json={
            "message": "Кнопка не работает",
            "page_path": "/courses",
            "attachment_ids": [attachment],
        },
        headers=student.headers,
    )
    assert created.status_code == 201, created.text
    feedback = created.json()
    assert feedback["status"] == "new"
    assert feedback["author_id"] == str(student.id)
    assert [item["id"] for item in feedback["attachments"]] == [attachment]

    listing = await client.get("/admin/feedback", params={"status": "new"}, headers=admin.headers)
    assert listing.status_code == 200
    assert [item["id"] for item in listing.json()["items"]] == [feedback["id"]]
    resolved_only = await client.get(
        "/admin/feedback", params={"status": "resolved"}, headers=admin.headers
    )
    assert resolved_only.json()["total"] == 0

    deleted = await client.delete(f"/admin/feedback/{feedback['id']}", headers=admin.headers)
    assert deleted.status_code == 204
    assert (await client.get("/admin/feedback", headers=admin.headers)).json()["total"] == 0
    missing = await client.delete(f"/admin/feedback/{feedback['id']}", headers=admin.headers)
    assert_error(missing, 404, "not_found")


async def test_feedback_status_update_of_missing_item(
    client: httpx.AsyncClient, admin: Actor
) -> None:
    response = await client.patch(
        f"/admin/feedback/{admin.id}", json={"status": "resolved"}, headers=admin.headers
    )

    assert_error(response, 404, "not_found")


@pytest.mark.xfail(
    strict=True,
    raises=MissingGreenlet,
    reason=(
        "БАГ: FeedbackService.set_status не обновляет объект после commit, а updated_at "
        "с server_onupdate протухает — сериализация ответа падает с MissingGreenlet (500)"
    ),
)
async def test_feedback_status_update(
    client: httpx.AsyncClient, student: Actor, admin: Actor
) -> None:
    created = await client.post("/feedback", json={"message": "Опечатка"}, headers=student.headers)

    response = await client.patch(
        f"/admin/feedback/{created.json()['id']}",
        json={"status": "resolved"},
        headers=admin.headers,
    )

    assert response.status_code == 200
    assert response.json()["status"] == "resolved"


async def test_feedback_rejects_foreign_attachment(
    client: httpx.AsyncClient, student: Actor, make_user: MakeUser
) -> None:
    other = await make_user(UserRole.STUDENT)
    foreign = await upload(client, other)

    response = await client.post(
        "/feedback",
        json={"message": "Чужой файл", "attachment_ids": [foreign]},
        headers=student.headers,
    )

    assert_error(response, 422, "invalid_update")
