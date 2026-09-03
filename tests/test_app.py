import json

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
    assert "/api/v1/feedback" in schema["paths"]
    assert "/api/v1/admin/feedback" in schema["paths"]
    assert "/api/v1/users" in schema["paths"]
    assert "/api/v1/users/{login}" in schema["paths"]
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


class _UniqueViolationError(Exception):
    """Форма ошибки asyncpg: имя ограничения лежит отдельным атрибутом."""

    def __init__(self, constraint_name: str) -> None:
        super().__init__("duplicate key value violates unique constraint")
        self.constraint_name = constraint_name


def test_known_constraint_names_the_field_that_clashed() -> None:
    error = IntegrityError("INSERT", {}, _UniqueViolationError("uq_quizzes_module_id_slug"))

    body = json.loads(bytes(exception_response(error).body))

    assert body["message"] == "В этом модуле уже есть тест с таким адресом"
    assert body["details"] == {"field": "slug"}


def test_constraint_name_is_read_through_the_driver_wrapper() -> None:
    """SQLAlchemy отдаёт ошибку адаптера драйвера, оригинал у неё в __cause__."""
    wrapped = ValueError("wrapped by the dbapi adapter")
    wrapped.__cause__ = _UniqueViolationError("uq_lessons_module_id_slug")
    error = IntegrityError("INSERT", {}, wrapped)

    body = json.loads(bytes(exception_response(error).body))

    assert body["message"] == "В этом модуле уже есть урок с таким адресом"


def test_unknown_constraint_keeps_the_generic_conflict() -> None:
    error = IntegrityError("INSERT", {}, _UniqueViolationError("uq_module_items_quiz_id"))

    body = json.loads(bytes(exception_response(error).body))

    assert body["message"] == "Объект с такими данными уже существует"
    assert body["details"] == {}
