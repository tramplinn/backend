import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.conftest import Actor, MakeUser
from tests.integration.fakes import Fakes
from tests.integration.helpers import assert_error, issued_email_code, query_param
from tramplin.models.enums import IdentityProvider
from tramplin.services.contracts import OAuthProfile

REFRESH_COOKIE = "tramplin_refresh"


def _profile(provider_id: str, login: str, email: str | None = None) -> OAuthProfile:
    return OAuthProfile(provider_id, login, login.title(), email, f"https://avatars.test/{login}")


def _replace_refresh_cookie(client: httpx.AsyncClient, token: str) -> None:
    client.cookies.clear()
    client.cookies.set(REFRESH_COOKIE, token)


async def _oauth_login(client: httpx.AsyncClient, fakes: Fakes, profile: OAuthProfile) -> str:
    """Проходит login → callback и возвращает access-токен, полученный по refresh-куке."""
    fakes.github.profiles[f"code-{profile.provider_id}"] = profile
    login = await client.get("/auth/github/login", params={"next_path": "/courses"})
    assert login.status_code == 200
    state = query_param(login.json()["authorize_url"], "state")

    callback = await client.get(
        "/auth/github/callback", params={"code": f"code-{profile.provider_id}", "state": state}
    )
    assert callback.status_code == 303
    assert callback.headers["location"] == "http://localhost:5173/courses"
    assert client.cookies.get(REFRESH_COOKIE)

    refreshed = await client.post("/auth/refresh")
    assert refreshed.status_code == 200, refreshed.text
    return str(refreshed.json()["access_token"])


async def test_providers_lists_configured_providers(client: httpx.AsyncClient) -> None:
    response = await client.get("/auth/providers")

    assert response.status_code == 200
    assert set(response.json()["providers"]) == {"github", "yandex", "gitlab"}


async def test_oauth_login_creates_user_and_session(
    client: httpx.AsyncClient, fakes: Fakes, db: AsyncEngine
) -> None:
    access = await _oauth_login(client, fakes, _profile("42", "octocat", "octo@example.com"))

    me = await client.get("/auth/me", headers={"Authorization": f"Bearer {access}"})
    assert me.status_code == 200
    body = me.json()
    assert body["login"] == "octocat"
    assert body["email"] == "octo@example.com"
    assert [identity["provider"] for identity in body["identities"]] == ["github"]
    async with db.connect() as conn:
        assert (await conn.execute(text("SELECT count(*) FROM refresh_tokens"))).scalar() == 1


async def test_callback_rejects_unknown_state(client: httpx.AsyncClient) -> None:
    response = await client.get("/auth/github/callback", params={"code": "c", "state": "forged"})

    assert_error(response, 401, "invalid_oauth_state")


async def test_refresh_rotates_cookie_and_old_token_stops_working(
    client: httpx.AsyncClient, fakes: Fakes
) -> None:
    await _oauth_login(client, fakes, _profile("1", "rotator"))
    first = client.cookies[REFRESH_COOKIE]

    second = await client.post("/auth/refresh")
    assert second.status_code == 200
    assert client.cookies[REFRESH_COOKIE] != first

    _replace_refresh_cookie(client, first)
    assert (await client.post("/auth/refresh")).status_code == 401


async def test_refresh_without_cookie_is_unauthorized(client: httpx.AsyncClient) -> None:
    response = await client.post("/auth/refresh")

    assert response.status_code == 401


async def test_logout_revokes_current_session(client: httpx.AsyncClient, fakes: Fakes) -> None:
    await _oauth_login(client, fakes, _profile("2", "leaver"))
    token = client.cookies[REFRESH_COOKIE]

    response = await client.post("/auth/logout")

    assert response.status_code == 204
    _replace_refresh_cookie(client, token)
    assert (await client.post("/auth/refresh")).status_code == 401


async def test_logout_all_revokes_every_session(
    client: httpx.AsyncClient, fakes: Fakes, db: AsyncEngine
) -> None:
    access = await _oauth_login(client, fakes, _profile("3", "everywhere"))
    await client.post("/auth/refresh")

    response = await client.post("/auth/logout/all", headers={"Authorization": f"Bearer {access}"})

    assert response.status_code == 204
    async with db.connect() as conn:
        assert (await conn.execute(text("SELECT count(*) FROM refresh_tokens"))).scalar() == 0


async def test_logout_all_requires_auth(client: httpx.AsyncClient) -> None:
    assert (await client.post("/auth/logout/all")).status_code == 401


async def test_link_second_provider(
    client: httpx.AsyncClient, fakes: Fakes, student: Actor
) -> None:
    fakes.yandex.profiles["ya-code"] = _profile("ya-1", "student-on-yandex")
    link = await client.get("/auth/yandex/link", headers=student.headers)
    assert link.status_code == 200
    state = query_param(link.json()["authorize_url"], "state")

    callback = await client.get("/auth/yandex/callback", params={"code": "ya-code", "state": state})
    assert callback.status_code == 303

    me = await client.get("/auth/me", headers=student.headers)
    assert {identity["provider"] for identity in me.json()["identities"]} == {"github", "yandex"}


async def test_link_requires_auth(client: httpx.AsyncClient) -> None:
    assert (await client.get("/auth/gitlab/link")).status_code == 401


async def test_unlink_identity(client: httpx.AsyncClient, make_user: MakeUser) -> None:
    user = await make_user(identities=(IdentityProvider.GITHUB, IdentityProvider.GITLAB))

    response = await client.delete("/auth/identities/gitlab", headers=user.headers)

    assert response.status_code == 204
    me = await client.get("/auth/me", headers=user.headers)
    assert [identity["provider"] for identity in me.json()["identities"]] == ["github"]


async def test_unlink_last_identity_is_conflict(client: httpx.AsyncClient, student: Actor) -> None:
    response = await client.delete("/auth/identities/github", headers=student.headers)

    assert_error(response, 409, "conflict")


async def test_email_login_registers_new_user(
    client: httpx.AsyncClient, redis: Redis, db: AsyncEngine
) -> None:
    start = await client.post("/auth/email/start", json={"email": "New@Example.com"})
    assert start.status_code == 204
    async with db.connect() as conn:
        outbox = (await conn.execute(text("SELECT to_email FROM email_job_outbox"))).scalars()
        assert list(outbox) == ["new@example.com"]

    code = await issued_email_code(redis, "new@example.com")
    verify = await client.post(
        "/auth/email/verify", json={"email": "new@example.com", "code": code}
    )

    assert verify.status_code == 200, verify.text
    assert client.cookies.get(REFRESH_COOKIE)
    me = await client.get(
        "/auth/me", headers={"Authorization": f"Bearer {verify.json()['access_token']}"}
    )
    assert me.json()["email"] == "new@example.com"


async def test_email_start_has_cooldown(client: httpx.AsyncClient) -> None:
    await client.post("/auth/email/start", json={"email": "spam@example.com"})

    response = await client.post("/auth/email/start", json={"email": "spam@example.com"})

    assert_error(response, 429, "too_many_requests")


async def test_email_verify_rejects_wrong_code(client: httpx.AsyncClient) -> None:
    await client.post("/auth/email/start", json={"email": "who@example.com"})

    response = await client.post(
        "/auth/email/verify", json={"email": "who@example.com", "code": "000000"}
    )

    # Шанс, что случайный код совпал с 000000, — один на миллион.
    assert_error(response, 401, "invalid_email_code")


async def test_email_link(client: httpx.AsyncClient, redis: Redis, student: Actor) -> None:
    start = await client.post(
        "/auth/email/link/start", json={"email": "linked@example.com"}, headers=student.headers
    )
    assert start.status_code == 204
    code = await issued_email_code(redis, "linked@example.com")

    verify = await client.post(
        "/auth/email/link/verify",
        json={"email": "linked@example.com", "code": code},
        headers=student.headers,
    )

    assert verify.status_code == 204, verify.text
    me = await client.get("/auth/me", headers=student.headers)
    assert "email" in {identity["provider"] for identity in me.json()["identities"]}


async def test_me_requires_auth(client: httpx.AsyncClient) -> None:
    assert_error(await client.get("/auth/me"), 401, "unauthorized")


async def test_me_rejects_garbage_token(client: httpx.AsyncClient) -> None:
    response = await client.get("/auth/me", headers={"Authorization": "Bearer nope"})

    assert response.status_code == 401


async def test_update_profile_creates_directory_entries(
    client: httpx.AsyncClient, student: Actor
) -> None:
    response = await client.patch(
        "/auth/me",
        json={
            "name": "Ада",
            "headline": "Учусь",
            "specialty": "backend",
            "grade": "junior",
            "experience_years": 1,
            "company": "Tramplin",
            "university": "МГУ",
            "interests": ["Python", "SQL"],
        },
        headers=student.headers,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["name"] == "Ада"
    assert body["company"]["name"] == "Tramplin"
    assert body["university"]["name"] == "МГУ"
    assert sorted(interest["name"] for interest in body["interests"]) == ["Python", "SQL"]


async def test_update_profile_validates_input(client: httpx.AsyncClient, student: Actor) -> None:
    response = await client.patch(
        "/auth/me", json={"experience_years": 100}, headers=student.headers
    )

    assert_error(response, 422, "validation_error")


async def test_update_profile_stores_preferred_locale(
    client: httpx.AsyncClient, student: Actor
) -> None:
    me = await client.get("/auth/me", headers=student.headers)
    assert me.json()["preferred_locale"] is None

    response = await client.patch(
        "/auth/me", json={"preferred_locale": "en"}, headers=student.headers
    )

    assert response.status_code == 200, response.text
    assert response.json()["preferred_locale"] == "en"
    me = await client.get("/auth/me", headers=student.headers)
    assert me.json()["preferred_locale"] == "en"


async def test_update_profile_rejects_unknown_locale(
    client: httpx.AsyncClient, student: Actor
) -> None:
    response = await client.patch(
        "/auth/me", json={"preferred_locale": "de"}, headers=student.headers
    )

    assert_error(response, 422, "validation_error")


@pytest.mark.parametrize("path", ["/companies", "/universities", "/interests"])
async def test_directories(client: httpx.AsyncClient, student: Actor, path: str) -> None:
    await client.patch(
        "/auth/me",
        json={"company": "Acme", "university": "ИТМО", "interests": ["Go"]},
        headers=student.headers,
    )

    response = await client.get(path, headers=student.headers)

    assert response.status_code == 200
    assert len(response.json()) == 1


async def test_directories_require_auth(client: httpx.AsyncClient) -> None:
    assert (await client.get("/companies")).status_code == 401
