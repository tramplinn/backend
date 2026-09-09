import logging
from typing import Final
from urllib.parse import urlencode

import httpx

from tramplin.core.config import Settings
from tramplin.core.errors import OAuthProviderError
from tramplin.infrastructure.oauth_http import as_object, body, text
from tramplin.services.contracts import OAuthProfile

logger = logging.getLogger(__name__)

PROVIDER_NAME: Final = "GitLab"
OAUTH_BASE_URL: Final = "https://gitlab.com/oauth"
API_BASE_URL: Final = "https://gitlab.com/api/v4"
SCOPE: Final = "read_user"


class GitLabOAuthClient:
    """Access-токен провайдера используется один раз для профиля и не сохраняется."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient) -> None:
        self._settings = settings
        self._client = client

    def authorize_url(self, state: str) -> str:
        query = urlencode(
            {
                "response_type": "code",
                "client_id": self._settings.gitlab_client_id,
                "redirect_uri": self._settings.gitlab_redirect_uri,
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
                "client_id": self._settings.gitlab_client_id,
                "client_secret": self._settings.gitlab_client_secret.get_secret_value(),
                "redirect_uri": self._settings.gitlab_redirect_uri,
            },
        )
        payload = as_object(body(response, PROVIDER_NAME), PROVIDER_NAME)
        token = text(payload.get("access_token"))
        if token is None:
            logger.warning("gitlab oauth code exchange failed: %s", payload.get("error"))
            raise OAuthProviderError("GitLab не выдал access-токен")
        return token

    async def fetch_profile(self, access_token: str) -> OAuthProfile:
        response = await self._client.get(
            f"{API_BASE_URL}/user",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        return _parse_profile(as_object(body(response, PROVIDER_NAME), PROVIDER_NAME))


def _parse_profile(payload: dict[str, object]) -> OAuthProfile:
    provider_id = payload.get("id")
    login = text(payload.get("username"))
    if provider_id is None or login is None:
        raise OAuthProviderError("GitLab вернул профиль без id или username")
    return OAuthProfile(
        provider_id=str(provider_id),
        login=login,
        name=text(payload.get("name")),
        email=text(payload.get("email")),
        avatar_url=text(payload.get("avatar_url")),
    )
