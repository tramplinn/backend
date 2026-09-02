import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.exc import IntegrityError

from tramplin.api.errors import exception_response
from tramplin.core.config import Settings
from tramplin.main import create_app


@pytest.fixture
async def client(settings: Settings) -> httpx.AsyncClient:
    app = create_app(settings)
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def test_health_endpoint_reports_ok(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/health")

    assert response.status_code == httpx.codes.OK
    assert response.json() == {"status": "ok"}


async def test_me_without_token_returns_structured_401(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/auth/me")

    assert response.status_code == httpx.codes.UNAUTHORIZED
    assert response.json()["code"] == "unauthorized"
    assert response.headers["www-authenticate"] == "Bearer"


async def test_me_with_garbage_token_returns_invalid_token(client: httpx.AsyncClient) -> None:
    response = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer not-a-jwt"},
    )

    assert response.status_code == httpx.codes.UNAUTHORIZED
    assert response.json()["code"] == "invalid_token"


async def test_openapi_exposes_auth_routes(settings: Settings) -> None:
    schema = create_app(settings).openapi()

    assert "/api/v1/auth/{provider}/login" in schema["paths"]
    assert "/api/v1/auth/{provider}/callback" in schema["paths"]
    assert "/api/v1/auth/providers" in schema["paths"]
    assert "/api/v1/auth/refresh" in schema["paths"]
    assert "/api/v1/courses" in schema["paths"]
    assert "/api/v1/courses/{slug}" in schema["paths"]
    assert "/api/v1/courses/{slug}/module-dependencies" in schema["paths"]
    assert "/api/v1/courses/{slug}/progress" in schema["paths"]
    assert "/api/v1/lessons/{lesson_id}/interview-cards" in schema["paths"]
    assert "/api/v1/progress/lessons/{lesson_id}" in schema["paths"]
    assert "/api/v1/quizzes/{quiz_id}/attempts" in schema["paths"]
    assert "/api/v1/authoring/courses" in schema["paths"]
    assert "/api/v1/tracks" in schema["paths"]
    assert "/api/v1/authoring/modules/{module_id}/dependencies" in schema["paths"]
    assert "/api/v1/authoring/modules/{module_id}/order" in schema["paths"]
    assert "/api/v1/authoring/modules/{module_id}/lessons/order" not in schema["paths"]
    assert "/api/v1/authoring/modules/{module_id}/quizzes/order" not in schema["paths"]
    assert "/api/v1/authoring/courses/{slug}/module-dependencies" in schema["paths"]
    assert "/api/v1/authoring/tracks/{track_id}/courses/order" in schema["paths"]
    assert "/api/v1/authoring/tracks/{track_id}/courses/{course_id}" in schema["paths"]
    assert "/api/v1/authoring/markdown/preview" in schema["paths"]
    assert "/api/v1/admin/users" in schema["paths"]
    assert "/api/v1/assets" in schema["paths"]
    assert "/api/v1/admin/groups" not in schema["paths"]

    user_parameters = schema["paths"]["/api/v1/admin/users"]["get"]["parameters"]
    assert {parameter["name"] for parameter in user_parameters} >= {
        "q",
        "role",
        "is_active",
        "limit",
        "offset",
    }


async def test_validation_error_has_public_error_schema(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/auth/github/login", params={"next_path": "external"})

    assert response.status_code == httpx.codes.UNPROCESSABLE_ENTITY
    assert response.json()["code"] == "validation_error"
    assert response.json()["details"]["fields"]


async def test_unhandled_error_has_safe_response(settings: Settings) -> None:
    app: FastAPI = create_app(settings)

    @app.get("/raise-unhandled-error")
    async def raise_unhandled_error() -> None:
        raise RuntimeError("sensitive details")

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/raise-unhandled-error")

    assert response.status_code == httpx.codes.INTERNAL_SERVER_ERROR
    assert response.json() == {
        "code": "internal_error",
        "message": "Внутренняя ошибка",
        "details": {},
    }
    assert "sensitive details" not in response.text


def test_integrity_error_is_mapped_to_conflict() -> None:
    error = IntegrityError("INSERT", {}, ValueError("duplicate"))

    response = exception_response(error)

    assert response.status_code == httpx.codes.CONFLICT
    assert b"duplicate" not in response.body
