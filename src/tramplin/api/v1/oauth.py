import base64
from urllib.parse import parse_qs

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse

from tramplin.api.dependencies import BearerCredentials, TeacherUser
from tramplin.api.schemas.auth import (
    McpAuthorizationApprovalOut,
    McpAuthorizationRequestOut,
    McpIntrospectionOut,
)
from tramplin.core.errors import InvalidTokenError
from tramplin.core.time import utc_now
from tramplin.services.mcp_oauth import McpOAuthError, McpOAuthService

router = APIRouter(prefix="/oauth", tags=["oauth"], route_class=DishkaRoute)


@router.get(
    "/authorize",
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
    "/requests/{request_id}",
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
    "/requests/{request_id}/approve",
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
    "/requests/{request_id}/deny",
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
    "/token",
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
    "/introspect",
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
    "/revoke",
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
