from typing import Annotated

from dishka.integrations.fastapi import FromDishka, inject
from fastapi import Depends, params
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from tramplin.core.errors import AuthError
from tramplin.models.enums import UserRole
from tramplin.models.users import User
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


TeacherUser = Annotated[User, require_role(UserRole.TEACHER)]
AdminUser = Annotated[User, require_role(UserRole.ADMIN)]
