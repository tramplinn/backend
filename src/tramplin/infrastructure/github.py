import logging
from typing import Final
from urllib.parse import urlencode

import httpx

from tramplin.core.config import Settings
from tramplin.core.errors import OAuthProviderError
from tramplin.infrastructure.oauth_http import as_object, body, text
from tramplin.services.contracts import OAuthProfile

logger = logging.getLogger(__name__)

PROVIDER_NAME: Final = "GitHub"
OAUTH_BASE_URL: Final = "https://github.com"
API_BASE_URL: Final = "https://api.github.com"
SCOPE: Final = "read:user user:email"
API_HEADERS: Final = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}


class GitHubOAuthClient:
    """Access-токен провайдера используется один раз для профиля и не сохраняется."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient) -> None:
        self._settings = settings
        self._client = client

    def authorize_url(self, state: str) -> str:
        query = urlencode(
            {
                "client_id": self._settings.github_client_id,
                "redirect_uri": self._settings.github_redirect_uri,
                "scope": SCOPE,
                "state": state,
                "allow_signup": "false",
            },
        )
        return f"{OAUTH_BASE_URL}/login/oauth/authorize?{query}"

    async def exchange_code(self, code: str) -> str:
        response = await self._client.post(
            f"{OAUTH_BASE_URL}/login/oauth/access_token",
            data={
                "client_id": self._settings.github_client_id,
                "client_secret": self._settings.github_client_secret.get_secret_value(),
                "code": code,
                "redirect_uri": self._settings.github_redirect_uri,
            },
            headers={"Accept": "application/json"},
        )
        payload = as_object(body(response, PROVIDER_NAME), PROVIDER_NAME)
        token = text(payload.get("access_token"))
        if token is None:
            logger.warning("github oauth code exchange failed: %s", payload.get("error"))
            raise OAuthProviderError("GitHub не выдал access-токен")
        return token

    async def fetch_profile(self, access_token: str) -> OAuthProfile:
        headers = API_HEADERS | {"Authorization": f"Bearer {access_token}"}
        response = await self._client.get(f"{API_BASE_URL}/user", headers=headers)
        payload = as_object(body(response, PROVIDER_NAME), PROVIDER_NAME)
        profile = _parse_profile(payload)
        if profile.email is not None:
            return profile
        return replace_email(profile, await self._fetch_primary_email(headers))

    async def _fetch_primary_email(self, headers: dict[str, str]) -> str | None:
        """Скрытый в настройках email лежит в отдельном ресурсе; его отсутствие не ошибка."""
        response = await self._client.get(f"{API_BASE_URL}/user/emails", headers=headers)
        if response.status_code != httpx.codes.OK:
            return None
        entries = body(response, PROVIDER_NAME, strict=False)
        if not isinstance(entries, list):
            return None
        return next(
            (
                email
                for entry in entries
                if isinstance(entry, dict)
                and entry.get("primary")
                and entry.get("verified")
                and (email := text(entry.get("email")))
            ),
            None,
        )


def replace_email(profile: OAuthProfile, email: str | None) -> OAuthProfile:
    return OAuthProfile(
        provider_id=profile.provider_id,
        login=profile.login,
        name=profile.name,
        email=email,
        avatar_url=profile.avatar_url,
    )


def _parse_profile(payload: dict[str, object]) -> OAuthProfile:
    provider_id = payload.get("id")
    login = text(payload.get("login"))
    if provider_id is None or login is None:
        raise OAuthProviderError("GitHub вернул профиль без id или login")
    return OAuthProfile(
        provider_id=str(provider_id),
        login=login,
        name=text(payload.get("name")),
        email=text(payload.get("email")),
        avatar_url=text(payload.get("avatar_url")),
    )
