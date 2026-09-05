from typing import Annotated

from dishka.integrations.fastapi import FromDishka, inject
from fastapi import Depends, params
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from tramplin.core.errors import AuthError, InvalidTokenError
from tramplin.models.enums import UserRole
from tramplin.models.users import User
from tramplin.services.mcp_oauth import McpOAuthError, McpOAuthService
from tramplin.services.session import SessionService
from tramplin.services.users import ensure_role

bearer_scheme = HTTPBearer(auto_error=False)

BearerCredentials = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)]


@inject
async def get_current_user(
    credentials: BearerCredentials,
    sessions: FromDishka[SessionService],
) -> User:
    """@inject нужен явно: DishkaRoute разбирает только сам обработчик, но не Depends в нём."""
    if credentials is None or not credentials.credentials:
        raise AuthError
    return await sessions.authenticate(credentials.credentials)


CurrentUser = Annotated[User, Depends(get_current_user)]


@inject
async def get_optional_user(
    credentials: BearerCredentials,
    sessions: FromDishka[SessionService],
) -> User | None:
    """Протухший токен переводит в гостя, а не в 401 посреди урока."""
    if credentials is None or not credentials.credentials:
        return None
    try:
        return await sessions.authenticate(credentials.credentials)
    except AuthError:
        return None


OptionalUser = Annotated[User | None, Depends(get_optional_user)]


def require_role(minimum: UserRole) -> params.Depends:
    """Роль читается из свежей записи в БД, а не из токена: понижение прав действует сразу."""

    async def dependency(user: CurrentUser) -> User:
        ensure_role(user, minimum)
        return user

    return params.Depends(dependency)


@inject
async def get_authoring_user(
    credentials: BearerCredentials,
    sessions: FromDishka[SessionService],
    mcp_oauth: FromDishka[McpOAuthService],
) -> User:
    """Только для /authoring/*: сюда же стучится MCP-сервер со своим access-token'ом.

    Bearer бывает двух видов: обычная сессия (JWT из SessionService) и MCP access-token
    (непрозрачный, из McpOAuthService) — второй пробуем, только если первый не похож на
    валидный JWT. Нарочно не трогаем общий get_current_user/CurrentUser/AdminUser: MCP
    выдаёт токен со scope=authoring и не должен давать доступ к admin- и student-эндпоинтам.
    """
    if credentials is None or not credentials.credentials:
        raise AuthError
    try:
        user = await sessions.authenticate(credentials.credentials)
    except InvalidTokenError:
        try:
            user = await mcp_oauth.introspect(credentials.credentials)
        except McpOAuthError as error:
            raise InvalidTokenError from error
    ensure_role(user, UserRole.TEACHER)
    return user


TeacherUser = Annotated[User, Depends(get_authoring_user)]
AdminUser = Annotated[User, require_role(UserRole.ADMIN)]
