from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from dishka.integrations.fastapi import setup_dishka
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from tramplin.api.errors import register_error_handlers
from tramplin.api.v1 import api_router
from tramplin.core.config import API_PREFIX, Settings, load_settings
from tramplin.core.di import build_container
from tramplin.logging import configure_logging


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield
    await app.state.dishka_container.close()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    configure_logging(debug=not settings.is_production)

    app = FastAPI(
        title="Tramplin API",
        version="0.1.0",
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_base_url],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router, prefix=API_PREFIX)
    register_error_handlers(app)
    setup_dishka(build_container(settings), app)
    return app
