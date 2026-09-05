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


@router.get("/providers")
async def providers(registry: FromDishka[OAuthRegistry]) -> ProvidersOut:
    """Фронт рисует кнопки по этому списку: непрописанного провайдера в нём нет."""
    return ProvidersOut(providers=registry.available)


@router.get("/{provider}/login")
async def provider_login(
    provider: IdentityProvider,
    registry: FromDishka[OAuthRegistry],
    next_path: NextPath = "/",
) -> AuthorizeUrlOut:
    url = await registry.get(provider).start_login(next_path)
    return AuthorizeUrlOut(authorize_url=url)


@router.get("/{provider}/link")
async def provider_link(
    provider: IdentityProvider,
    user: CurrentUser,
    registry: FromDishka[OAuthRegistry],
    next_path: NextPath = "/",
) -> AuthorizeUrlOut:
    """Привязка второго способа входа — только явным действием залогиненного пользователя."""
    url = await registry.get(provider).start_link(user.id, next_path)
    return AuthorizeUrlOut(authorize_url=url)


@router.get("/{provider}/callback")
async def provider_callback(
    provider: IdentityProvider,
    code: OAuthParam,
    state: OAuthParam,
    registry: FromDishka[OAuthRegistry],
    settings: FromDishka[Settings],
) -> RedirectResponse:
    """Токены не уезжают в URL: refresh кладём в куку, access фронт берёт через /auth/refresh."""
    result = await registry.get(provider).complete_callback(code, state)
    response = RedirectResponse(
        url=f"{settings.frontend_base_url}{result.next_path}",
        status_code=status.HTTP_303_SEE_OTHER,
    )
    set_refresh_cookie(response, settings, result.tokens.refresh_token)
    return response


@router.post("/refresh")
async def refresh(
    response: Response,
    sessions: FromDishka[SessionService],
    settings: FromDishka[Settings],
    refresh_token: RefreshCookie = None,
) -> AccessTokenOut:
    tokens = await sessions.refresh(refresh_token or "")
    set_refresh_cookie(response, settings, tokens.refresh_token)
    return AccessTokenOut(access_token=tokens.access_token, expires_at=tokens.access_expires_at)


@router.get("/mcp/authorize")
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


@router.get("/mcp/requests/{request_id}")
async def get_mcp_authorization_request(
    request_id: str,
    user: TeacherUser,
    oauth: FromDishka[McpOAuthService],
) -> McpAuthorizationRequestOut:
    authorization = await oauth.get_request(request_id, user)
    return McpAuthorizationRequestOut(client_name="MCP-клиент", scope=authorization.scope)


@router.post("/mcp/requests/{request_id}/approve")
async def approve_mcp_authorization(
    request_id: str,
    user: TeacherUser,
    oauth: FromDishka[McpOAuthService],
) -> McpAuthorizationApprovalOut:
    return McpAuthorizationApprovalOut(redirect_url=await oauth.approve(request_id, user))


@router.post("/mcp/requests/{request_id}/deny")
async def deny_mcp_authorization(
    request_id: str,
    user: TeacherUser,
    oauth: FromDishka[McpOAuthService],
) -> McpAuthorizationApprovalOut:
    return McpAuthorizationApprovalOut(redirect_url=await oauth.deny(request_id, user))


@router.post("/mcp/token")
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


@router.get("/mcp/introspect")
async def introspect_mcp_token(
    credentials: BearerCredentials,
    oauth: FromDishka[McpOAuthService],
) -> McpIntrospectionOut:
    try:
        user = await oauth.introspect(credentials.credentials if credentials else "")
    except McpOAuthError as error:
        raise InvalidTokenError from error
    return McpIntrospectionOut(sub=str(user.id), login=user.login, role=user.role.value)


@router.post("/mcp/revoke")
async def revoke_mcp_token(request: Request, oauth: FromDishka[McpOAuthService]) -> Response:
    form = _urlencoded(await request.body())
    try:
        client_id, client_secret = _basic_client(request.headers.get("authorization"))
        oauth.authenticate_client(client_id, client_secret)
    except McpOAuthError as error:
        return _oauth_error(error)
    await oauth.revoke(form.get("token", ""))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    sessions: FromDishka[SessionService],
    settings: FromDishka[Settings],
    refresh_token: RefreshCookie = None,
) -> None:
    await sessions.logout(refresh_token)
    clear_refresh_cookie(response, settings)


@router.post("/logout/all", status_code=status.HTTP_204_NO_CONTENT)
async def logout_everywhere(
    user: CurrentUser,
    response: Response,
    sessions: FromDishka[SessionService],
    settings: FromDishka[Settings],
) -> None:
    await sessions.logout_everywhere(user.id)
    clear_refresh_cookie(response, settings)


@router.get("/me")
async def me(user: CurrentUser, users: FromDishka[UserService]) -> MeOut:
    return MeOut.model_validate(await users.get_profile(user.id))


@router.patch("/me")
async def update_me(
    payload: UserProfileUpdate,
    user: CurrentUser,
    users: FromDishka[UserService],
) -> MeOut:
    updated = await users.update_profile(user.id, payload.model_dump(exclude_unset=True))
    return MeOut.model_validate(updated)


@router.delete("/identities/{provider}", status_code=status.HTTP_204_NO_CONTENT)
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
