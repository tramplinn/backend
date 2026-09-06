import base64
from typing import Annotated, Final
from urllib.parse import parse_qs

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Cookie, Query, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse

from tramplin.api.cookies import REFRESH_COOKIE_NAME, clear_refresh_cookie, set_refresh_cookie
from tramplin.api.dependencies import BearerCredentials, CurrentUser, TeacherUser
from tramplin.api.schemas import AccessTokenOut, AuthorizeUrlOut, MeOut, ProvidersOut
from tramplin.api.schemas.auth import (
    McpAuthorizationApprovalOut,
    McpAuthorizationRequestOut,
    McpIntrospectionOut,
)
from tramplin.api.schemas.users import UserProfileUpdate
from tramplin.core.config import Settings
from tramplin.core.errors import InvalidTokenError
from tramplin.core.time import utc_now
from tramplin.models.enums import IdentityProvider
from tramplin.services.mcp_oauth import McpOAuthError, McpOAuthService
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


@router.get(
    "/mcp/authorize",
    summary="OAuth authorization endpoint для MCP",
    description=(
        "Начало authorization_code + PKCE потока для MCP-клиентов: редиректит на "
        "страницу подтверждения доступа преподавателю, уже вошедшему на сайте."
    ),
)
async def authorize_mcp(
    oauth: FromDishka[McpOAuthService],
    response_type: str,
    client_id: str,
    redirect_uri: str,
    state: str,
    code_challenge: str,
    code_challenge_method: str,
    scope: str = "authoring",
) -> Response:
    try:
        url = await oauth.start_authorization(
            response_type=response_type,
            client_id=client_id,
            redirect_uri=redirect_uri,
            state=state,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            scope=scope,
        )
    except McpOAuthError as error:
        return _oauth_error(error)
    return RedirectResponse(url, status_code=status.HTTP_303_SEE_OTHER)


@router.get(
    "/mcp/requests/{request_id}",
    summary="Данные запроса на авторизацию MCP",
    description="Для страницы подтверждения: какой клиент и с каким scope просит доступ.",
)
async def get_mcp_authorization_request(
    request_id: str,
    user: TeacherUser,
    oauth: FromDishka[McpOAuthService],
) -> McpAuthorizationRequestOut:
    authorization = await oauth.get_request(request_id, user)
    return McpAuthorizationRequestOut(client_name="MCP-клиент", scope=authorization.scope)


@router.post(
    "/mcp/requests/{request_id}/approve",
    summary="Подтвердить авторизацию MCP",
    description="Преподаватель разрешает доступ; ответ содержит redirect_url для завершения.",
)
async def approve_mcp_authorization(
    request_id: str,
    user: TeacherUser,
    oauth: FromDishka[McpOAuthService],
) -> McpAuthorizationApprovalOut:
    return McpAuthorizationApprovalOut(redirect_url=await oauth.approve(request_id, user))


@router.post(
    "/mcp/requests/{request_id}/deny",
    summary="Отклонить авторизацию MCP",
    description="Преподаватель отклоняет доступ; ответ содержит redirect_url для завершения.",
)
async def deny_mcp_authorization(
    request_id: str,
    user: TeacherUser,
    oauth: FromDishka[McpOAuthService],
) -> McpAuthorizationApprovalOut:
    return McpAuthorizationApprovalOut(redirect_url=await oauth.deny(request_id, user))


@router.post(
    "/mcp/token",
    summary="OAuth token endpoint для MCP",
    description=(
        "Обменивает authorization_code (+ code_verifier) или refresh_token на пару "
        "токенов доступа; клиент аутентифицируется Basic-заголовком. "
        "Тело — application/x-www-form-urlencoded по спецификации OAuth 2.0, а не JSON."
    ),
)
async def mcp_token(request: Request, oauth: FromDishka[McpOAuthService]) -> JSONResponse:
    form = _urlencoded(await request.body())
    try:
        client_id, client_secret = _basic_client(request.headers.get("authorization"))
        oauth.authenticate_client(client_id, client_secret)
        grant_type = form.get("grant_type", "")
        if grant_type == "authorization_code":
            tokens = await oauth.exchange_code(
                form.get("code", ""),
                form.get("redirect_uri", ""),
                form.get("code_verifier", ""),
            )
        elif grant_type == "refresh_token":
            tokens = await oauth.refresh(form.get("refresh_token", ""))
        else:
            raise McpOAuthError("unsupported_grant_type")
    except McpOAuthError as error:
        return _oauth_error(error)
    return JSONResponse(
        {
            "access_token": tokens.access_token,
            "token_type": "Bearer",
            "expires_in": oauth.expires_in(tokens.access_expires_at, utc_now()),
            "refresh_token": tokens.refresh_token,
            "scope": "authoring",
        },
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )


@router.get(
    "/mcp/introspect",
    summary="Проверить MCP access-токен",
    description="Используется MCP-сервером для валидации входящих запросов и определения роли.",
)
async def introspect_mcp_token(
    credentials: BearerCredentials,
    oauth: FromDishka[McpOAuthService],
) -> McpIntrospectionOut:
    try:
        user = await oauth.introspect(credentials.credentials if credentials else "")
    except McpOAuthError as error:
        raise InvalidTokenError from error
    return McpIntrospectionOut(sub=str(user.id), login=user.login, role=user.role.value)


@router.post(
    "/mcp/revoke",
    summary="Отозвать MCP-токен",
    description="OAuth 2.0 token revocation: клиент аутентифицируется Basic-заголовком.",
)
async def revoke_mcp_token(request: Request, oauth: FromDishka[McpOAuthService]) -> Response:
    form = _urlencoded(await request.body())
    try:
        client_id, client_secret = _basic_client(request.headers.get("authorization"))
        oauth.authenticate_client(client_id, client_secret)
    except McpOAuthError as error:
        return _oauth_error(error)
    await oauth.revoke(form.get("token", ""))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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


def _urlencoded(body: bytes) -> dict[str, str]:
    return {key: values[-1] for key, values in parse_qs(body.decode()).items() if values}


def _basic_client(authorization: str | None) -> tuple[str, str]:
    try:
        scheme, encoded = (authorization or "").split(" ", 1)
        client_id, client_secret = base64.b64decode(encoded, validate=True).decode().split(":", 1)
    except (ValueError, UnicodeDecodeError) as error:
        raise McpOAuthError("invalid_client") from error
    if scheme.lower() != "basic":
        raise McpOAuthError("invalid_client")
    return client_id, client_secret


def _oauth_error(error: McpOAuthError) -> JSONResponse:
    status_code = (
        status.HTTP_401_UNAUTHORIZED
        if error.code == "invalid_client"
        else status.HTTP_400_BAD_REQUEST
    )
    return JSONResponse({"error": error.code}, status_code=status_code)
