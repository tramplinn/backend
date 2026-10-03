"""Проекты: каталог, права по ролям, участники, приглашения и витрина в профиле."""

from datetime import UTC, datetime
from typing import Any

import httpx
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.conftest import Actor, MakeUser
from tests.integration.helpers import assert_error, create
from tests.integration.test_people import upload

ALL_BLOCKS = ["about", "projects", "stats", "courses", "resume"]


async def new_project(
    client: httpx.AsyncClient,
    owner: Actor,
    title: str = "Мой проект",
    visibility: str = "public",
    **extra: Any,
) -> dict[str, Any]:
    return await create(
        client, "/projects", {"title": title, "visibility": visibility, **extra}, owner.headers
    )


async def invite(
    client: httpx.AsyncClient, slug: str, inviter: Actor, login: str, role: str, **extra: Any
) -> dict[str, Any]:
    return await create(
        client,
        f"/projects/{slug}/invites",
        {"login": login, "role": role, **extra},
        inviter.headers,
    )


async def join(
    client: httpx.AsyncClient, slug: str, inviter: Actor, member: Actor, role: str
) -> dict[str, Any]:
    sent = await invite(client, slug, inviter, member.login, role)
    accepted = await client.post(f"/me/invites/{sent['id']}/accept", headers=member.headers)
    assert accepted.status_code == 200, accepted.text
    return dict(accepted.json())


def roles(members: list[dict[str, Any]]) -> dict[str, str]:
    return {item["login"]: item["role"] for item in members}


# --- Создание и чтение ----------------------------------------------------------


async def test_create_project_makes_owner_and_free_slug(
    client: httpx.AsyncClient, student: Actor
) -> None:
    first = await new_project(client, student, title="  Мой проект  ", visibility="private")
    second = await new_project(client, student)

    assert first["slug"] == "moi-proekt"
    assert second["slug"] == "moi-proekt-2"
    assert first["title"] == "Мой проект"
    assert first["status"] == "idea"
    assert first["visibility"] == "private"
    assert first["readme_md"] == ""
    assert first["links"] == []
    assert first["my_role"] == "owner"
    assert first["members_count"] == 1
    assert roles(first["members"]) == {student.login: "owner"}

    fetched = await client.get("/projects/moi-proekt", headers=student.headers)
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["id"] == first["id"]


async def test_create_project_defaults_to_private(
    client: httpx.AsyncClient, student: Actor
) -> None:
    created = await create(client, "/projects", {"title": "Draft"}, student.headers)

    assert created["visibility"] == "private"
    assert_error(await client.get(f"/projects/{created['slug']}"), 404, "not_found")


async def test_create_project_requires_auth(client: httpx.AsyncClient) -> None:
    assert (await client.post("/projects", json={"title": "x"})).status_code == 401


async def test_visibility_controls_project_access(
    client: httpx.AsyncClient, student: Actor, make_user: MakeUser, admin: Actor
) -> None:
    stranger = await make_user()
    public = await new_project(client, student, title="Public", visibility="public")
    members_only = await new_project(client, student, title="Auth", visibility="authenticated")
    private = await new_project(client, student, title="Secret", visibility="private")

    anonymous = await client.get(f"/projects/{public['slug']}")
    assert anonymous.status_code == 200
    assert anonymous.json()["my_role"] is None
    assert_error(await client.get(f"/projects/{members_only['slug']}"), 404, "not_found")
    assert (
        await client.get(f"/projects/{members_only['slug']}", headers=stranger.headers)
    ).status_code == 200
    # Скрытый проект — 404, а не 403: сам факт существования не раскрываем.
    assert_error(
        await client.get(f"/projects/{private['slug']}", headers=stranger.headers),
        404,
        "not_found",
    )
    assert_error(
        await client.get(f"/projects/{private['slug']}/members", headers=stranger.headers),
        404,
        "not_found",
    )
    as_admin = await client.get(f"/projects/{private['slug']}", headers=admin.headers)
    assert as_admin.status_code == 200
    assert as_admin.json()["my_role"] == "owner"
    assert_error(await client.get("/projects/missing", headers=student.headers), 404, "not_found")


async def test_catalog_filters_search_and_sort(
    client: httpx.AsyncClient, student: Actor, make_user: MakeUser
) -> None:
    other = await make_user(login="catalog-other")
    zebra = await new_project(client, student, title="Zebra", summary="Мессенджер на Go")
    alpha = await new_project(client, other, title="Alpha", visibility="authenticated")
    await new_project(client, student, title="Hidden", visibility="private")
    await client.put(
        f"/projects/{zebra['slug']}/links",
        json={"links": [{"kind": "repository", "url": "https://git.test/zebra"}]},
        headers=student.headers,
    )
    await client.post(
        f"/projects/{alpha['slug']}/status", json={"status": "done"}, headers=other.headers
    )

    anonymous = await client.get("/projects")
    assert anonymous.status_code == 200, anonymous.text
    assert [item["slug"] for item in anonymous.json()["items"]] == [zebra["slug"]]
    assert anonymous.json()["items"][0]["my_role"] is None

    signed_in = await client.get("/projects", params={"sort": "title"}, headers=student.headers)
    assert signed_in.json()["total"] == 2
    assert [item["title"] for item in signed_in.json()["items"]] == ["Alpha", "Zebra"]

    async def slugs(**params: Any) -> list[str]:
        response = await client.get("/projects", params=params, headers=student.headers)
        assert response.status_code == 200, response.text
        return [item["slug"] for item in response.json()["items"]]

    assert await slugs(q="мессенджер") == [zebra["slug"]]
    assert await slugs(status=["done"]) == [alpha["slug"]]
    assert await slugs(status=["idea", "done"], sort="title") == [alpha["slug"], zebra["slug"]]
    assert await slugs(link_kind=["repository"]) == [zebra["slug"]]
    assert await slugs(link_kind=["repository", "demo"]) == []
    assert await slugs(member="catalog-other") == [alpha["slug"]]
    assert await slugs(limit=1, offset=1, sort="title") == [zebra["slug"]]


# --- Правка, статус, ссылки -----------------------------------------------------


async def test_update_project_fields_by_role(
    client: httpx.AsyncClient, student: Actor, make_user: MakeUser
) -> None:
    contributor = await make_user()
    viewer = await make_user()
    project = await new_project(client, student, title="Editable")
    slug = project["slug"]
    await join(client, slug, student, contributor, "contributor")
    await join(client, slug, student, viewer, "viewer")

    readme = await client.patch(
        f"/projects/{slug}",
        json={"readme_md": "# Привет", "summary": "Кратко"},
        headers=contributor.headers,
    )
    assert readme.status_code == 200, readme.text
    assert readme.json()["readme_md"] == "# Привет"
    assert readme.json()["summary"] == "Кратко"
    assert readme.json()["my_role"] == "contributor"

    assert_error(
        await client.patch(f"/projects/{slug}", json={"title": "New"}, headers=contributor.headers),
        403,
        "forbidden",
    )
    assert_error(
        await client.patch(f"/projects/{slug}", json={"readme_md": "x"}, headers=viewer.headers),
        403,
        "forbidden",
    )

    renamed = await client.patch(
        f"/projects/{slug}",
        json={"title": "Renamed", "slug": "renamed", "visibility": "authenticated"},
        headers=student.headers,
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["slug"] == "renamed"
    assert renamed.json()["visibility"] == "authenticated"
    assert (await client.get(f"/projects/{slug}", headers=student.headers)).status_code == 404
    assert (await client.get("/projects/renamed", headers=student.headers)).status_code == 200


async def test_update_project_validation(client: httpx.AsyncClient, student: Actor) -> None:
    project = await new_project(client, student, title="One")
    await new_project(client, student, title="Two")

    taken = await client.patch(
        f"/projects/{project['slug']}", json={"slug": "two"}, headers=student.headers
    )
    assert_error(taken, 409, "conflict")
    bad_slug = await client.patch(
        f"/projects/{project['slug']}", json={"slug": "Bad Slug"}, headers=student.headers
    )
    assert_error(bad_slug, 422, "validation_error")
    null_title = await client.patch(
        f"/projects/{project['slug']}", json={"title": None}, headers=student.headers
    )
    assert_error(null_title, 422, "invalid_update")


async def test_project_logo(client: httpx.AsyncClient, student: Actor) -> None:
    project = await new_project(client, student)
    logo = await upload(client, student)

    updated = await client.patch(
        f"/projects/{project['slug']}", json={"logo_asset_id": logo}, headers=student.headers
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["logo_asset_id"] == logo
    assert updated.json()["logo_url"].endswith(".png")

    cleared = await client.patch(
        f"/projects/{project['slug']}", json={"logo_asset_id": None}, headers=student.headers
    )
    assert cleared.json()["logo_asset_id"] is None
    assert cleared.json()["logo_url"] is None

    pdf = await client.post(
        "/assets",
        files={"file": ("cv.pdf", b"%PDF-1.7 test", "application/pdf")},
        data={"mime": "application/pdf"},
        headers=student.headers,
    )
    rejected = await client.patch(
        f"/projects/{project['slug']}",
        json={"logo_asset_id": pdf.json()["id"]},
        headers=student.headers,
    )
    assert_error(rejected, 422, "invalid_update")


async def test_status_changes_are_recorded(
    client: httpx.AsyncClient, student: Actor, make_user: MakeUser
) -> None:
    contributor = await make_user()
    project = await new_project(client, student)
    slug = project["slug"]
    await join(client, slug, student, contributor, "contributor")

    changed = await client.post(
        f"/projects/{slug}/status", json={"status": "in_progress"}, headers=student.headers
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["status"] == "in_progress"
    assert changed.json()["status_changed_at"] > project["status_changed_at"]
    # Повтор того же статуса не пишет событие.
    await client.post(
        f"/projects/{slug}/status", json={"status": "in_progress"}, headers=student.headers
    )
    assert_error(
        await client.post(
            f"/projects/{slug}/status", json={"status": "done"}, headers=contributor.headers
        ),
        403,
        "forbidden",
    )

    events = await client.get(f"/projects/{slug}/status-events")
    assert events.status_code == 200, events.text
    assert [(item["from_status"], item["to_status"]) for item in events.json()] == [
        ("idea", "in_progress"),
        (None, "idea"),
    ]
    assert {item["actor_login"] for item in events.json()} == {student.login}


async def test_status_events_hidden_for_private_project(
    client: httpx.AsyncClient, student: Actor
) -> None:
    project = await new_project(client, student, visibility="private")

    assert_error(await client.get(f"/projects/{project['slug']}/status-events"), 404, "not_found")


async def test_archived_project_is_read_only(
    client: httpx.AsyncClient, student: Actor, make_user: MakeUser
) -> None:
    other = await make_user()
    project = await new_project(client, student)
    slug = project["slug"]
    await client.post(
        f"/projects/{slug}/status", json={"status": "archived"}, headers=student.headers
    )

    assert_error(
        await client.patch(f"/projects/{slug}", json={"readme_md": "x"}, headers=student.headers),
        409,
        "conflict",
    )
    assert_error(
        await client.put(f"/projects/{slug}/links", json={"links": []}, headers=student.headers),
        409,
        "conflict",
    )
    assert_error(
        await client.post(
            f"/projects/{slug}/invites",
            json={"login": other.login, "role": "viewer"},
            headers=student.headers,
        ),
        409,
        "conflict",
    )
    # Смена статуса — единственный выход из архива.
    restored = await client.post(
        f"/projects/{slug}/status", json={"status": "paused"}, headers=student.headers
    )
    assert restored.status_code == 200
    assert (
        await client.patch(f"/projects/{slug}", json={"readme_md": "x"}, headers=student.headers)
    ).status_code == 200


async def test_replace_links_keeps_order(
    client: httpx.AsyncClient, student: Actor, make_user: MakeUser
) -> None:
    viewer = await make_user()
    project = await new_project(client, student)
    slug = project["slug"]
    await join(client, slug, student, viewer, "viewer")
    links = [
        {"kind": "demo", "url": "https://demo.test", "label": "Демо"},
        {"kind": "repository", "url": " https://git.test/repo "},
    ]

    replaced = await client.put(
        f"/projects/{slug}/links", json={"links": links}, headers=student.headers
    )
    assert replaced.status_code == 200, replaced.text
    body = replaced.json()["links"]
    assert [(item["kind"], item["url"], item["position"]) for item in body] == [
        ("demo", "https://demo.test", 0),
        ("repository", "https://git.test/repo", 1),
    ]
    assert body[0]["label"] == "Демо"

    shrunk = await client.put(
        f"/projects/{slug}/links", json={"links": links[1:]}, headers=student.headers
    )
    assert [item["kind"] for item in shrunk.json()["links"]] == ["repository"]

    assert_error(
        await client.put(
            f"/projects/{slug}/links",
            json={"links": [{"kind": "demo", "url": "javascript:alert(1)"}]},
            headers=student.headers,
        ),
        422,
        "validation_error",
    )
    assert_error(
        await client.put(f"/projects/{slug}/links", json={"links": []}, headers=viewer.headers),
        403,
        "forbidden",
    )


async def test_delete_project_only_by_owner(
    client: httpx.AsyncClient, student: Actor, make_user: MakeUser, db: AsyncEngine
) -> None:
    maintainer = await make_user()
    project = await new_project(client, student)
    slug = project["slug"]
    await join(client, slug, student, maintainer, "maintainer")

    assert_error(
        await client.delete(f"/projects/{slug}", headers=maintainer.headers), 403, "forbidden"
    )
    assert (await client.delete(f"/projects/{slug}", headers=student.headers)).status_code == 204
    assert (await client.get(f"/projects/{slug}")).status_code == 404
    async with db.connect() as conn:
        for table in ("project_members", "project_status_events", "project_invites"):
            count = await conn.scalar(text(f"SELECT count(*) FROM {table}"))  # noqa: S608
            assert count == 0, table


# --- Участники ------------------------------------------------------------------


async def test_member_roles_and_titles(
    client: httpx.AsyncClient, student: Actor, make_user: MakeUser
) -> None:
    maintainer = await make_user()
    contributor = await make_user()
    project = await new_project(client, student)
    slug = project["slug"]
    await join(client, slug, student, maintainer, "maintainer")
    await join(client, slug, maintainer, contributor, "contributor")

    members = await client.get(f"/projects/{slug}/members")
    assert members.status_code == 200, members.text
    assert roles(members.json()) == {
        student.login: "owner",
        maintainer.login: "maintainer",
        contributor.login: "contributor",
    }

    own_title = await client.patch(
        f"/projects/{slug}/members/{contributor.login}",
        json={"title": "Фронтенд"},
        headers=contributor.headers,
    )
    assert own_title.status_code == 200, own_title.text
    by_login = {item["login"]: item for item in own_title.json()}
    assert by_login[contributor.login]["title"] == "Фронтенд"

    assert_error(
        await client.patch(
            f"/projects/{slug}/members/{maintainer.login}",
            json={"title": "x"},
            headers=contributor.headers,
        ),
        403,
        "forbidden",
    )
    assert_error(
        await client.patch(
            f"/projects/{slug}/members/{contributor.login}",
            json={"role": "viewer"},
            headers=maintainer.headers,
        ),
        403,
        "forbidden",
    )
    assert_error(
        await client.patch(
            f"/projects/{slug}/members/{contributor.login}",
            json={"role": "owner"},
            headers=student.headers,
        ),
        409,
        "conflict",
    )
    assert_error(
        await client.patch(
            f"/projects/{slug}/members/nobody", json={"title": "x"}, headers=student.headers
        ),
        404,
        "not_found",
    )

    demoted = await client.patch(
        f"/projects/{slug}/members/{contributor.login}",
        json={"role": "viewer"},
        headers=student.headers,
    )
    assert roles(demoted.json())[contributor.login] == "viewer"


async def test_remove_member_and_leave(
    client: httpx.AsyncClient, student: Actor, make_user: MakeUser
) -> None:
    first = await make_user()
    second = await make_user()
    leaver = await make_user()
    project = await new_project(client, student)
    slug = project["slug"]
    for member in (first, second):
        await join(client, slug, student, member, "maintainer")
    await join(client, slug, student, leaver, "contributor")

    assert_error(
        await client.delete(f"/projects/{slug}/members/{second.login}", headers=first.headers),
        403,
        "forbidden",
    )
    assert_error(
        await client.delete(f"/projects/{slug}/members/{student.login}", headers=student.headers),
        409,
        "conflict",
    )
    assert (
        await client.delete(f"/projects/{slug}/members/{leaver.login}", headers=leaver.headers)
    ).status_code == 204
    assert (
        await client.delete(f"/projects/{slug}/members/{second.login}", headers=student.headers)
    ).status_code == 204

    members = await client.get(f"/projects/{slug}/members")
    assert roles(members.json()) == {student.login: "owner", first.login: "maintainer"}
    mine = await client.get("/me/projects", headers=leaver.headers)
    assert mine.json() == []


async def test_transfer_ownership(
    client: httpx.AsyncClient, student: Actor, make_user: MakeUser, db: AsyncEngine
) -> None:
    heir = await make_user()
    outsider = await make_user()
    project = await new_project(client, student)
    slug = project["slug"]
    await join(client, slug, student, heir, "contributor")

    assert_error(
        await client.post(
            f"/projects/{slug}/transfer", json={"login": student.login}, headers=heir.headers
        ),
        403,
        "forbidden",
    )
    assert_error(
        await client.post(
            f"/projects/{slug}/transfer", json={"login": outsider.login}, headers=student.headers
        ),
        404,
        "not_found",
    )
    assert_error(
        await client.post(
            f"/projects/{slug}/transfer", json={"login": student.login}, headers=student.headers
        ),
        409,
        "conflict",
    )

    transferred = await client.post(
        f"/projects/{slug}/transfer", json={"login": heir.login}, headers=student.headers
    )
    assert transferred.status_code == 200, transferred.text
    assert transferred.json()["my_role"] == "maintainer"
    assert roles(transferred.json()["members"]) == {
        student.login: "maintainer",
        heir.login: "owner",
    }
    async with db.connect() as conn:
        owners = await conn.scalar(
            text("SELECT count(*) FROM project_members WHERE role = 'owner'")
        )
    assert owners == 1


async def test_transfer_to_inactive_user_is_rejected(
    client: httpx.AsyncClient, student: Actor, make_user: MakeUser, db: AsyncEngine
) -> None:
    heir = await make_user()
    project = await new_project(client, student)
    await join(client, project["slug"], student, heir, "maintainer")
    async with db.begin() as conn:
        await conn.execute(
            text("UPDATE users SET is_active = false WHERE id = :id"), {"id": heir.id}
        )

    response = await client.post(
        f"/projects/{project['slug']}/transfer", json={"login": heir.login}, headers=student.headers
    )

    assert_error(response, 409, "conflict")


async def test_inactive_members_hidden_from_outsiders(
    client: httpx.AsyncClient, student: Actor, make_user: MakeUser, db: AsyncEngine
) -> None:
    ghost = await make_user()
    project = await new_project(client, student)
    await join(client, project["slug"], student, ghost, "contributor")
    async with db.begin() as conn:
        await conn.execute(
            text("UPDATE users SET is_active = false WHERE id = :id"), {"id": ghost.id}
        )

    outside = await client.get(f"/projects/{project['slug']}")
    assert outside.json()["members_count"] == 1
    assert ghost.login not in roles(outside.json()["members"])
    inside = await client.get(f"/projects/{project['slug']}/members", headers=student.headers)
    assert ghost.login in roles(inside.json())


# --- Приглашения ----------------------------------------------------------------


async def test_invite_accept_flow_sends_email(
    client: httpx.AsyncClient, student: Actor, make_user: MakeUser, db: AsyncEngine
) -> None:
    invitee = await make_user(email="invitee@example.com")
    project = await new_project(client, student, title="Команда", visibility="private")
    slug = project["slug"]

    sent = await invite(client, slug, student, invitee.login, "contributor", title="Дизайн")
    assert sent["status"] == "pending"
    assert sent["invitee_login"] == invitee.login
    assert sent["inviter_login"] == student.login
    assert sent["project"]["slug"] == slug
    assert sent["title"] == "Дизайн"

    async with db.connect() as conn:
        email = (
            await conn.execute(text("SELECT to_email, category, queue FROM email_job_outbox"))
        ).one()
    assert tuple(email) == ("invitee@example.com", "project_invite", "transactional")

    pending = await client.get(f"/projects/{slug}/invites", headers=student.headers)
    assert [item["id"] for item in pending.json()] == [sent["id"]]
    incoming = await client.get("/me/invites", headers=invitee.headers)
    assert [item["id"] for item in incoming.json()] == [sent["id"]]

    accepted = await client.post(f"/me/invites/{sent['id']}/accept", headers=invitee.headers)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["my_role"] == "contributor"
    assert accepted.json()["members_count"] == 2

    project_view = await client.get(f"/projects/{slug}", headers=invitee.headers)
    assert project_view.status_code == 200
    member = next(m for m in project_view.json()["members"] if m["login"] == invitee.login)
    assert member["title"] == "Дизайн"
    assert (await client.get("/me/invites", headers=invitee.headers)).json() == []
    assert (await client.get(f"/projects/{slug}/invites", headers=student.headers)).json() == []
    again = await client.post(f"/me/invites/{sent['id']}/accept", headers=invitee.headers)
    assert_error(again, 409, "conflict")


async def test_invite_without_email_skips_outbox(
    client: httpx.AsyncClient, student: Actor, make_user: MakeUser, db: AsyncEngine
) -> None:
    invitee = await make_user()
    project = await new_project(client, student)

    await invite(client, project["slug"], student, invitee.login, "viewer")

    async with db.connect() as conn:
        assert await conn.scalar(text("SELECT count(*) FROM email_job_outbox")) == 0


async def test_invite_rules(client: httpx.AsyncClient, student: Actor, make_user: MakeUser) -> None:
    maintainer = await make_user()
    invitee = await make_user()
    inactive = await make_user(is_active=False)
    project = await new_project(client, student)
    slug = project["slug"]
    await join(client, slug, student, maintainer, "maintainer")

    async def attempt(actor: Actor, login: str, role: str) -> httpx.Response:
        return await client.post(
            f"/projects/{slug}/invites", json={"login": login, "role": role}, headers=actor.headers
        )

    assert_error(await attempt(student, invitee.login, "owner"), 422, "validation_error")
    assert_error(await attempt(maintainer, invitee.login, "maintainer"), 403, "forbidden")
    assert_error(await attempt(student, "nobody", "viewer"), 404, "not_found")
    assert_error(await attempt(student, inactive.login, "viewer"), 404, "not_found")
    assert_error(await attempt(student, student.login, "viewer"), 409, "conflict")
    assert_error(await attempt(student, maintainer.login, "viewer"), 409, "conflict")

    assert (await attempt(maintainer, invitee.login, "contributor")).status_code == 201
    assert_error(await attempt(student, invitee.login, "viewer"), 409, "conflict")

    assert_error(
        await client.get(f"/projects/{slug}/invites", headers=invitee.headers), 403, "forbidden"
    )


async def test_decline_and_reinvite(
    client: httpx.AsyncClient, student: Actor, make_user: MakeUser
) -> None:
    invitee = await make_user()
    stranger = await make_user()
    project = await new_project(client, student)
    slug = project["slug"]
    sent = await invite(client, slug, student, invitee.login, "viewer")

    foreign = await client.post(f"/me/invites/{sent['id']}/decline", headers=stranger.headers)
    assert_error(foreign, 404, "not_found")
    declined = await client.post(f"/me/invites/{sent['id']}/decline", headers=invitee.headers)
    assert declined.status_code == 204
    assert_error(
        await client.post(f"/me/invites/{sent['id']}/accept", headers=invitee.headers),
        409,
        "conflict",
    )

    again = await invite(client, slug, student, invitee.login, "contributor")
    assert again["id"] != sent["id"]


async def test_revoke_invite(
    client: httpx.AsyncClient, student: Actor, make_user: MakeUser
) -> None:
    invitee = await make_user()
    other_owner = await make_user()
    project = await new_project(client, student)
    other = await new_project(client, other_owner, title="Other")
    sent = await invite(client, project["slug"], student, invitee.login, "viewer")

    assert_error(
        await client.delete(
            f"/projects/{other['slug']}/invites/{sent['id']}", headers=other_owner.headers
        ),
        404,
        "not_found",
    )
    revoked = await client.delete(
        f"/projects/{project['slug']}/invites/{sent['id']}", headers=student.headers
    )
    assert revoked.status_code == 204
    assert (await client.get("/me/invites", headers=invitee.headers)).json() == []
    assert_error(
        await client.delete(
            f"/projects/{project['slug']}/invites/{sent['id']}", headers=student.headers
        ),
        409,
        "conflict",
    )
    assert_error(
        await client.post(f"/me/invites/{sent['id']}/accept", headers=invitee.headers),
        409,
        "conflict",
    )


async def test_expired_invite_is_closed_on_read(
    client: httpx.AsyncClient, student: Actor, make_user: MakeUser, db: AsyncEngine
) -> None:
    invitee = await make_user()
    project = await new_project(client, student)
    sent = await invite(client, project["slug"], student, invitee.login, "viewer")
    async with db.begin() as conn:
        await conn.execute(
            text("UPDATE project_invites SET expires_at = now() - interval '1 minute'")
        )

    assert (await client.get("/me/invites", headers=invitee.headers)).json() == []
    async with db.connect() as conn:
        status = await conn.scalar(
            text("SELECT status FROM project_invites WHERE id = :id"), {"id": sent["id"]}
        )
    assert status == "expired"
    assert_error(
        await client.post(f"/me/invites/{sent['id']}/accept", headers=invitee.headers),
        409,
        "conflict",
    )
    # Просроченное не мешает пригласить заново.
    await invite(client, project["slug"], student, invitee.login, "viewer")


async def test_invite_hourly_quota(
    client: httpx.AsyncClient, student: Actor, make_user: MakeUser, redis: Redis
) -> None:
    invitee = await make_user()
    project = await new_project(client, student)
    await redis.set(f"projects:invites:{datetime.now(UTC):%Y-%m-%dT%H}:{student.id}", 30)

    response = await client.post(
        f"/projects/{project['slug']}/invites",
        json={"login": invitee.login, "role": "viewer"},
        headers=student.headers,
    )

    assert_error(response, 429, "too_many_requests")
    assert (await client.get("/me/invites", headers=invitee.headers)).json() == []


# --- Мои проекты и профиль ------------------------------------------------------


async def test_my_projects_and_profile_order(
    client: httpx.AsyncClient, student: Actor, make_user: MakeUser
) -> None:
    viewer = await make_user()
    first = await new_project(client, student, title="First")
    second = await new_project(client, student, title="Second", visibility="private")
    third = await new_project(client, student, title="Third")

    mine = await client.get("/me/projects", headers=student.headers)
    assert mine.status_code == 200, mine.text
    assert [item["slug"] for item in mine.json()] == ["first", "second", "third"]
    assert all(item["show_in_profile"] for item in mine.json())

    order = [
        {"project_id": third["id"]},
        {"project_id": first["id"], "show_in_profile": False},
        {"project_id": second["id"]},
    ]
    saved = await client.put("/me/projects/order", json={"items": order}, headers=student.headers)
    assert saved.status_code == 204, saved.text
    mine = await client.get("/me/projects", headers=student.headers)
    assert [(item["slug"], item["show_in_profile"]) for item in mine.json()] == [
        ("third", True),
        ("first", False),
        ("second", True),
    ]

    # Чужой профиль: скрытый в профиле и private-проекты не видны.
    profile = await client.get(f"/users/{student.login}", headers=viewer.headers)
    assert profile.status_code == 200, profile.text
    assert [item["slug"] for item in profile.json()["projects"]] == ["third"]
    own = await client.get(f"/users/{student.login}", headers=student.headers)
    assert [item["slug"] for item in own.json()["projects"]] == ["third", "second"]

    assert_error(
        await client.put("/me/projects/order", json={"items": order[:2]}, headers=student.headers),
        409,
        "conflict",
    )
    assert_error(
        await client.put(
            "/me/projects/order", json={"items": [*order, order[0]]}, headers=student.headers
        ),
        409,
        "conflict",
    )
    assert_error(
        await client.put(
            "/me/projects/order",
            json={"items": [*order[:2], {"project_id": str(viewer.id)}]},
            headers=student.headers,
        ),
        409,
        "conflict",
    )


async def test_catalog_member_filter_respects_show_in_profile(
    client: httpx.AsyncClient, student: Actor
) -> None:
    project = await new_project(client, student)
    await client.put(
        "/me/projects/order",
        json={"items": [{"project_id": project["id"], "show_in_profile": False}]},
        headers=student.headers,
    )

    response = await client.get("/projects", params={"member": student.login})

    assert response.json()["total"] == 0


async def test_profile_layout_defaults_and_save(
    client: httpx.AsyncClient, student: Actor, make_user: MakeUser
) -> None:
    viewer = await make_user()
    await client.patch("/auth/me", json={"bio": "Пишу на Go"}, headers=student.headers)

    default = await client.get("/me/profile-layout", headers=student.headers)
    assert default.status_code == 200, default.text
    assert default.json()["blocks"] == [{"block": block, "visible": True} for block in ALL_BLOCKS]
    profile = await client.get(f"/users/{student.login}", headers=viewer.headers)
    assert profile.json()["layout"] == ALL_BLOCKS
    assert profile.json()["bio"] == "Пишу на Go"
    assert profile.json()["completed_lessons"] == 0

    blocks = [
        {"block": "projects", "visible": True},
        {"block": "about", "visible": False},
        {"block": "courses", "visible": True},
        {"block": "stats", "visible": False},
        {"block": "resume", "visible": True},
    ]
    saved = await client.put("/me/profile-layout", json={"blocks": blocks}, headers=student.headers)
    assert saved.status_code == 200, saved.text
    assert saved.json()["blocks"] == blocks
    assert (await client.get("/me/profile-layout", headers=student.headers)).json()[
        "blocks"
    ] == blocks

    # Перестановка поверх сохранённой раскладки не упирается в уникальность позиций.
    reordered = list(reversed(blocks))
    again = await client.put(
        "/me/profile-layout", json={"blocks": reordered}, headers=student.headers
    )
    assert again.status_code == 200, again.text
    assert again.json()["blocks"] == reordered

    profile = await client.get(f"/users/{student.login}", headers=viewer.headers)
    body = profile.json()
    assert body["layout"] == ["resume", "courses", "projects"]
    assert body["bio"] is None
    assert body["interests"] == []
    assert body["completed_lessons"] is None
    assert body["passed_quizzes"] is None
    assert body["solved_algorithms"] is None


async def test_profile_hidden_projects_block(
    client: httpx.AsyncClient, student: Actor, make_user: MakeUser
) -> None:
    viewer = await make_user()
    await new_project(client, student)
    blocks = [{"block": block, "visible": block != "projects"} for block in ALL_BLOCKS]
    await client.put("/me/profile-layout", json={"blocks": blocks}, headers=student.headers)

    profile = await client.get(f"/users/{student.login}", headers=viewer.headers)

    assert "projects" not in profile.json()["layout"]
    assert profile.json()["projects"] == []


async def test_profile_layout_rejects_incomplete_or_duplicate(
    client: httpx.AsyncClient, student: Actor
) -> None:
    missing = [{"block": block} for block in ALL_BLOCKS[:-1]]
    duplicate = [*missing, {"block": "about"}]

    for blocks in (missing, duplicate):
        response = await client.put(
            "/me/profile-layout", json={"blocks": blocks}, headers=student.headers
        )
        assert_error(response, 422, "invalid_update")
    assert_error(
        await client.put(
            "/me/profile-layout", json={"blocks": [{"block": "unknown"}]}, headers=student.headers
        ),
        422,
        "validation_error",
    )


async def test_me_routes_require_auth(client: httpx.AsyncClient) -> None:
    for method, path in [
        ("GET", "/me/projects"),
        ("GET", "/me/invites"),
        ("GET", "/me/profile-layout"),
    ]:
        assert (await client.request(method, path)).status_code == 401, path
