from fastapi import APIRouter

from tramplin.api.v1.admin import router as admin_router
from tramplin.api.v1.assets import router as assets_router
from tramplin.api.v1.auth import router as auth_router
from tramplin.api.v1.authoring import router as authoring_router
from tramplin.api.v1.content import router as content_router
from tramplin.api.v1.health import router as health_router
from tramplin.api.v1.learning import router as learning_router
from tramplin.api.v1.tutor import router as tutor_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(content_router)
api_router.include_router(learning_router)
api_router.include_router(authoring_router)
api_router.include_router(admin_router)
api_router.include_router(assets_router)
api_router.include_router(tutor_router)

__all__ = ["api_router"]
