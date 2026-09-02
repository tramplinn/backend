import logging
from typing import Final
from urllib.parse import urlencode

import httpx

from tramplin.core.config import Settings
from tramplin.core.errors import OAuthProviderError
from tramplin.infrastructure.oauth_http import as_object, body, text
from tramplin.services.contracts import OAuthProfile

logger = logging.getLogger(__name__)

PROVIDER_NAME: Final = "Яндекс ID"
OAUTH_BASE_URL: Final = "https://oauth.yandex.ru"
API_BASE_URL: Final = "https://login.yandex.ru"
SCOPE: Final = "login:email login:info login:avatar"
AVATAR_URL: Final = "https://avatars.yandex.net/get-yapic/{avatar_id}/islands-200"


class YandexOAuthClient:
    """Access-токен провайдера используется один раз для профиля и не сохраняется."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient) -> None:
        self._settings = settings
        self._client = client

    def authorize_url(self, state: str) -> str:
        query = urlencode(
            {
                "response_type": "code",
                "client_id": self._settings.yandex_client_id,
                "redirect_uri": self._settings.yandex_redirect_uri,
                "scope": SCOPE,
                "state": state,
            },
        )
        return f"{OAUTH_BASE_URL}/authorize?{query}"

    async def exchange_code(self, code: str) -> str:
        response = await self._client.post(
            f"{OAUTH_BASE_URL}/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": self._settings.yandex_client_id,
                "client_secret": self._settings.yandex_client_secret.get_secret_value(),
                "redirect_uri": self._settings.yandex_redirect_uri,
            },
        )
        payload = as_object(body(response, PROVIDER_NAME), PROVIDER_NAME)
        token = text(payload.get("access_token"))
        if token is None:
            logger.warning("yandex oauth code exchange failed: %s", payload.get("error"))
            raise OAuthProviderError("Яндекс ID не выдал access-токен")
        return token

    async def fetch_profile(self, access_token: str) -> OAuthProfile:
        response = await self._client.get(
            f"{API_BASE_URL}/info",
            params={"format": "json"},
            headers={"Authorization": f"OAuth {access_token}"},
        )
        return _parse_profile(as_object(body(response, PROVIDER_NAME), PROVIDER_NAME))


def _parse_profile(payload: dict[str, object]) -> OAuthProfile:
    provider_id = text(payload.get("id"))
    login = text(payload.get("login"))
    if provider_id is None or login is None:
        raise OAuthProviderError("Яндекс ID вернул профиль без id или login")
    return OAuthProfile(
        provider_id=provider_id,
        login=login,
        name=text(payload.get("display_name")) or text(payload.get("real_name")),
        email=text(payload.get("default_email")),
        avatar_url=_avatar_url(payload),
    )


def _avatar_url(payload: dict[str, object]) -> str | None:
    """Яндекс отдаёт не ссылку, а идентификатор картинки, и флаг «аватара нет»."""
    if payload.get("is_avatar_empty") is True:
        return None
    avatar_id = text(payload.get("default_avatar_id"))
    return None if avatar_id is None else AVATAR_URL.format(avatar_id=avatar_id)
