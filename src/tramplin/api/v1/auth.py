from typing import Annotated, Final

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Cookie, Query, Response, status
from fastapi.responses import RedirectResponse

from tramplin.api.cookies import REFRESH_COOKIE_NAME, clear_refresh_cookie, set_refresh_cookie
from tramplin.api.dependencies import CurrentUser
from tramplin.api.schemas import AccessTokenOut, AuthorizeUrlOut, MeOut
from tramplin.core.config import Settings
from tramplin.models.enums import IdentityProvider
from tramplin.services.github_auth import GitHubAuthService
from tramplin.services.session import SessionService
from tramplin.services.users import UserService

router = APIRouter(prefix="/auth", tags=["auth"], route_class=DishkaRoute)

MAX_QUERY_LENGTH: Final = 512
NEXT_PATH_PATTERN: Final = r"^/[^\r\n]*$"

RefreshCookie = Annotated[str | None, Cookie(alias=REFRESH_COOKIE_NAME)]
NextPath = Annotated[str, Query(pattern=NEXT_PATH_PATTERN, max_length=MAX_QUERY_LENGTH)]
OAuthParam = Annotated[str, Query(max_length=MAX_QUERY_LENGTH)]


@router.get("/github/login")
async def github_login(
    github: FromDishka[GitHubAuthService],
    next_path: NextPath = "/",
) -> AuthorizeUrlOut:
    return AuthorizeUrlOut(authorize_url=await github.start_login(next_path))


@router.get("/github/link")
async def github_link(
    user: CurrentUser,
    github: FromDishka[GitHubAuthService],
    next_path: NextPath = "/",
) -> AuthorizeUrlOut:
    """Привязка второго способа входа — только явным действием залогиненного пользователя."""
    return AuthorizeUrlOut(authorize_url=await github.start_link(user.id, next_path))


@router.get("/github/callback")
async def github_callback(
    code: OAuthParam,
    state: OAuthParam,
    github: FromDishka[GitHubAuthService],
    settings: FromDishka[Settings],
) -> RedirectResponse:
    """Токены не уезжают в URL: refresh кладём в куку, access фронт берёт через /auth/refresh."""
    result = await github.complete_callback(code, state)
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


@router.delete("/identities/{provider}", status_code=status.HTTP_204_NO_CONTENT)
async def unlink_identity(
    provider: IdentityProvider,
    user: CurrentUser,
    users: FromDishka[UserService],
) -> None:
    await users.unlink_identity(user.id, provider)
