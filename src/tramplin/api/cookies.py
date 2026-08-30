from fastapi import Response

from tramplin.core.config import API_PREFIX, Settings

REFRESH_COOKIE_NAME = "tramplin_refresh"
COOKIE_PATH = f"{API_PREFIX}/auth"

GUEST_COOKIE_NAME = "tramplin_guest"
GUEST_COOKIE_PATH = f"{API_PREFIX}/tutor"


def set_refresh_cookie(response: Response, settings: Settings, token: str) -> None:
    """httpOnly + SameSite=Lax: токен недоступен из JS и не уходит по кросс-сайтовым POST."""
    response.set_cookie(
        REFRESH_COOKIE_NAME,
        token,
        max_age=int(settings.refresh_token_ttl.total_seconds()),
        path=COOKIE_PATH,
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
    )


def clear_refresh_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        REFRESH_COOKIE_NAME,
        path=COOKIE_PATH,
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
    )


def set_guest_cookie(response: Response, settings: Settings, guest_id: str) -> None:
    """Не подписана: куку и так можно стереть, от накрутки защищает лимит по адресу."""
    response.set_cookie(
        GUEST_COOKIE_NAME,
        guest_id,
        max_age=int(settings.guest_cookie_ttl.total_seconds()),
        path=GUEST_COOKIE_PATH,
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
    )
