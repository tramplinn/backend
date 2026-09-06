import uuid_utils.compat as uuid
from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query

from tramplin.api.dependencies import AdminUser
from tramplin.api.schemas.algorithms import RunnerHealthOut, RunnerLanguageOut, RunnerQueueOut
from tramplin.api.schemas.pagination import PageOut
from tramplin.api.schemas.users import UserAdminUpdate, UserOut
from tramplin.models.enums import UserRole
from tramplin.services.algorithms import AlgorithmOperationsService
from tramplin.services.users import UserService

router = APIRouter(prefix="/admin", tags=["admin"], route_class=DishkaRoute)


@router.get(
    "/users",
    summary="Список пользователей (админ)",
    description="Поиск и фильтрация всех пользователей, включая деактивированных.",
)
async def list_users(
    _: AdminUser,
    users: FromDishka[UserService],
    q: str | None = Query(default=None, max_length=200),
    role: UserRole | None = None,
    is_active: bool | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> PageOut[UserOut]:
    page = await users.list(
        query=q,
        role=role,
        is_active=is_active,
        limit=limit,
        offset=offset,
    )
    return PageOut(
        items=[UserOut.model_validate(user) for user in page.items],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


@router.patch(
    "/users/{user_id}",
    summary="Изменить пользователя (админ)",
    description="Меняет роль или статус активности пользователя.",
)
async def update_user(
    user_id: uuid.UUID,
    payload: UserAdminUpdate,
    admin: AdminUser,
    users: FromDishka[UserService],
) -> UserOut:
    user = await users.update(admin.id, user_id, payload.model_dump(exclude_unset=True))
    return UserOut.model_validate(user)


@router.get(
    "/code-runner/health",
    summary="Статус исполнителя кода",
    description="Доступность сервиса, запускающего решения алгоритмических задач.",
)
async def code_runner_health(
    _: AdminUser,
    service: FromDishka[AlgorithmOperationsService],
) -> RunnerHealthOut:
    health, languages = await service.health()
    return RunnerHealthOut(status=health, languages=languages)


@router.get(
    "/code-runner/languages",
    summary="Поддерживаемые языки исполнителя",
    description="Языки, доступные исполнителю кода на данный момент.",
)
async def code_runner_languages(
    _: AdminUser,
    service: FromDishka[AlgorithmOperationsService],
) -> list[RunnerLanguageOut]:
    return [RunnerLanguageOut.model_validate(item) for item in await service.languages()]


@router.get(
    "/code-runner/queue",
    summary="Очередь исполнителя кода",
    description="Число запущенных, ожидающих и не доставленных в очередь посылок.",
)
async def code_runner_queue(
    _: AdminUser,
    service: FromDishka[AlgorithmOperationsService],
) -> RunnerQueueOut:
    queued, running, pending_outbox = await service.queue()
    return RunnerQueueOut(
        queued=queued,
        running=running,
        pending_outbox=pending_outbox,
    )
