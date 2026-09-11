from typing import Annotated, Final

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Cookie, Query, Response, status
from fastapi.responses import RedirectResponse

from tramplin.api.cookies import REFRESH_COOKIE_NAME, clear_refresh_cookie, set_refresh_cookie
from tramplin.api.dependencies import CurrentUser
from tramplin.api.schemas import (
    AccessTokenOut,
    AuthorizeUrlOut,
    EmailStartIn,
    EmailVerifyIn,
    MeOut,
    ProvidersOut,
)
from tramplin.api.schemas.users import UserProfileUpdate
from tramplin.core.config import Settings
from tramplin.models.enums import IdentityProvider
from tramplin.services.email_auth import EmailAuthService
from tramplin.services.oauth_auth import OAuthRegistry
from tramplin.services.session import SessionService
from tramplin.services.users import UserService

router = APIRouter(prefix="/auth", tags=["auth"], route_class=DishkaRoute)

MAX_QUERY_LENGTH: Final = 512
NEXT_PATH_PATTERN: Final = r"^/[^\r\n]*$"

RefreshCookie = Annotated[str | None, Cookie(alias=REFRESH_COOKIE_NAME)]
NextPath = Annotated[str, Query(pattern=NEXT_PATH_PATTERN, max_length=MAX_QUERY_LENGTH)]
OAuthParam = Annotated[str, Query(max_length=MAX_QUERY_LENGTH)]


@router.get(
    "/providers",
    summary="Доступные способы входа",
    description="Фронт рисует кнопки по этому списку: непрописанного провайдера в нём нет.",
)
async def providers(registry: FromDishka[OAuthRegistry]) -> ProvidersOut:
    return ProvidersOut(providers=registry.available)


@router.get(
    "/{provider}/login",
    summary="Начать вход через провайдера",
    description="Возвращает URL авторизации провайдера, на который нужно перенаправить браузер.",
)
async def provider_login(
    provider: IdentityProvider,
    registry: FromDishka[OAuthRegistry],
    next_path: NextPath = "/",
) -> AuthorizeUrlOut:
    url = await registry.get(provider).start_login(next_path)
    return AuthorizeUrlOut(authorize_url=url)


@router.get(
    "/{provider}/link",
    summary="Привязать ещё один способ входа",
    description="Привязка второго провайдера — только явным действием залогиненного пользователя.",
)
async def provider_link(
    provider: IdentityProvider,
    user: CurrentUser,
    registry: FromDishka[OAuthRegistry],
    next_path: NextPath = "/",
) -> AuthorizeUrlOut:
    url = await registry.get(provider).start_link(user.id, next_path)
    return AuthorizeUrlOut(authorize_url=url)


@router.get(
    "/{provider}/callback",
    summary="Обратный вызов провайдера",
    description=(
        "Провайдер редиректит сюда после согласия пользователя. Токены не уезжают в "
        "URL: refresh кладётся в куку, access фронт берёт через /auth/refresh."
    ),
)
async def provider_callback(
    provider: IdentityProvider,
    code: OAuthParam,
    state: OAuthParam,
    registry: FromDishka[OAuthRegistry],
    settings: FromDishka[Settings],
) -> RedirectResponse:
    result = await registry.get(provider).complete_callback(code, state)
    response = RedirectResponse(
        url=f"{settings.frontend_base_url}{result.next_path}",
        status_code=status.HTTP_303_SEE_OTHER,
    )
    set_refresh_cookie(response, settings, result.tokens.refresh_token)
    return response


@router.post(
    "/refresh",
    summary="Обновить access-токен",
    description="По refresh-куке выдаёт новый access-токен и ротирует refresh-куку.",
)
async def refresh(
    response: Response,
    sessions: FromDishka[SessionService],
    settings: FromDishka[Settings],
    refresh_token: RefreshCookie = None,
) -> AccessTokenOut:
    tokens = await sessions.refresh(refresh_token or "")
    set_refresh_cookie(response, settings, tokens.refresh_token)
    return AccessTokenOut(access_token=tokens.access_token, expires_at=tokens.access_expires_at)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Выйти из текущей сессии",
    description="Отзывает refresh-токен текущей вкладки и очищает refresh-куку.",
)
async def logout(
    response: Response,
    sessions: FromDishka[SessionService],
    settings: FromDishka[Settings],
    refresh_token: RefreshCookie = None,
) -> None:
    await sessions.logout(refresh_token)
    clear_refresh_cookie(response, settings)


@router.post(
    "/logout/all",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Выйти на всех устройствах",
    description="Отзывает refresh-токены всех сессий пользователя, не только текущей.",
)
async def logout_everywhere(
    user: CurrentUser,
    response: Response,
    sessions: FromDishka[SessionService],
    settings: FromDishka[Settings],
) -> None:
    await sessions.logout_everywhere(user.id)
    clear_refresh_cookie(response, settings)


@router.post(
    "/email/start",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Отправить код для входа по почте",
    description="Письмо с кодом уходит в очередь; повторная отправка ограничена cooldown'ом.",
)
async def email_start(
    payload: EmailStartIn,
    email_auth: FromDishka[EmailAuthService],
) -> None:
    await email_auth.request_login_code(payload.email)


@router.post(
    "/email/verify",
    summary="Подтвердить код и войти",
    description="Существующий email — вход, новый — регистрация нового пользователя.",
)
async def email_verify(
    payload: EmailVerifyIn,
    response: Response,
    email_auth: FromDishka[EmailAuthService],
    settings: FromDishka[Settings],
) -> AccessTokenOut:
    result = await email_auth.verify_login_code(payload.email, payload.code)
    set_refresh_cookie(response, settings, result.tokens.refresh_token)
    return AccessTokenOut(
        access_token=result.tokens.access_token, expires_at=result.tokens.access_expires_at
    )


@router.post(
    "/email/link/start",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Отправить код для привязки почты",
    description="Код привязан к текущему пользователю: подтвердить его может только он.",
)
async def email_link_start(
    payload: EmailStartIn,
    user: CurrentUser,
    email_auth: FromDishka[EmailAuthService],
) -> None:
    await email_auth.request_link_code(user.id, payload.email)


@router.post(
    "/email/link/verify",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Подтвердить код и привязать почту",
    description="Почта — постоянный способ входа, не зависящий от внешних провайдеров.",
)
async def email_link_verify(
    payload: EmailVerifyIn,
    user: CurrentUser,
    email_auth: FromDishka[EmailAuthService],
) -> None:
    await email_auth.verify_link_code(user.id, payload.email, payload.code)


@router.get(
    "/me",
    summary="Текущий пользователь",
    description="Полный профиль вошедшего пользователя, включая приватные поля.",
)
async def me(user: CurrentUser, users: FromDishka[UserService]) -> MeOut:
    return MeOut.model_validate(await users.get_profile(user.id))


@router.patch(
    "/me",
    summary="Изменить свой профиль",
    description="Частичное обновление; передаются только изменённые поля.",
)
async def update_me(
    payload: UserProfileUpdate,
    user: CurrentUser,
    users: FromDishka[UserService],
) -> MeOut:
    updated = await users.update_profile(user.id, payload.model_dump(exclude_unset=True))
    return MeOut.model_validate(updated)


@router.delete(
    "/identities/{provider}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Отвязать способ входа",
    description="Отвязывает провайдера от аккаунта; последний способ входа отвязать нельзя.",
)
async def unlink_identity(
    provider: IdentityProvider,
    user: CurrentUser,
    users: FromDishka[UserService],
) -> None:
    await users.unlink_identity(user.id, provider)
