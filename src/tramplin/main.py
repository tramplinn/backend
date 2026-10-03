from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from dishka.integrations.fastapi import setup_dishka
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from tramplin.api.errors import register_error_handlers
from tramplin.api.schemas import ErrorOut
from tramplin.api.v1 import api_router
from tramplin.core.config import API_PREFIX, Settings, load_settings
from tramplin.core.di import build_container
from tramplin.logging import configure_logging

OPENAPI_TAGS: list[dict[str, str]] = [
    {"name": "health", "description": "Проверки живости и готовности сервиса."},
    {"name": "auth", "description": "Вход через OAuth-провайдеров, сессии, профиль."},
    {
        "name": "oauth",
        "description": (
            "OAuth 2.0 authorization server для MCP-клиентов: authorize/token/"
            "introspect/revoke и подтверждение доступа преподавателем."
        ),
    },
    {"name": "content", "description": "Публичный каталог: треки, курсы, уроки, тесты."},
    {"name": "news", "description": "Новостная лента."},
    {"name": "users", "description": "Профили пользователей (только для вошедших)."},
    {"name": "feedback", "description": "Обратная связь от пользователей."},
    {"name": "learning", "description": "Прогресс обучения и прохождение тестов."},
    {"name": "assets", "description": "Загрузка файлов (изображения, вложения)."},
    {"name": "tutor", "description": "AI-ассистент по урокам и задачам."},
    {"name": "algorithms", "description": "Практика по алгоритмическим задачам."},
    {"name": "recommendations", "description": "Персональные рекомендации курсов и задач."},
    {
        "name": "admin",
        "description": "Администрирование: пользователи, обратная связь, раннер кода.",
    },
    {
        "name": "authoring:tracks",
        "description": "Управление треками (для авторов курсов).",
    },
    {
        "name": "authoring:courses",
        "description": "Управление курсами, включая черновики.",
    },
    {"name": "authoring:modules", "description": "Управление модулями курса."},
    {"name": "authoring:lessons", "description": "Управление уроками и предпросмотр Markdown."},
    {"name": "authoring:quizzes", "description": "Управление тестами и вопросами."},
    {"name": "authoring:news", "description": "Управление новостями, включая черновики."},
    {
        "name": "authoring:algorithms",
        "description": "Управление алгоритмическими задачами и подборками.",
    },
    {
        "name": "authoring:course-plans",
        "description": "Массовое применение планов курса (используется MCP-сервером).",
    },
    {
        "name": "authoring:teacher-assistant",
        "description": "AI-помощник автора курса.",
    },
    {"name": "authoring:tags", "description": "Справочник тегов для контента."},
]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield
    await app.state.dishka_container.close()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    configure_logging(debug=not settings.is_production)

    app = FastAPI(
        title="Tramplin API",
        description="API учебной платформы Tramplin: курсы, уроки, тесты, прогресс, "
        "authoring, OAuth, файлы, AI-ассистент и алгоритмические задачи.",
        version="0.1.0",
        docs_url=None if settings.is_production else "/docs",
        openapi_url=None if settings.is_production else "/openapi.json",
        redoc_url=None,
        openapi_tags=OPENAPI_TAGS,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_base_url],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(
        api_router,
        prefix=API_PREFIX,
        responses={"default": {"model": ErrorOut, "description": "Ошибка"}},
    )
    register_error_handlers(app)
    setup_dishka(build_container(settings), app)
    return app
