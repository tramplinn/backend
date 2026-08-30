import logging
from typing import Final
from urllib.parse import urlencode

import httpx

from tramplin.core.config import Settings
from tramplin.core.errors import OAuthProviderError
from tramplin.services.contracts import GitHubProfile

logger = logging.getLogger(__name__)

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
        payload = _as_object(_body(response))
        token = _text(payload.get("access_token"))
        if token is None:
            logger.warning("github token exchange failed: %s", payload.get("error"))
            raise OAuthProviderError("GitHub не выдал access-токен")
        return token

    async def fetch_profile(self, access_token: str) -> GitHubProfile:
        headers = API_HEADERS | {"Authorization": f"Bearer {access_token}"}
        payload = _as_object(_body(await self._client.get(f"{API_BASE_URL}/user", headers=headers)))
        profile = _parse_profile(payload)
        if profile.email is not None:
            return profile
        return replace_email(profile, await self._fetch_primary_email(headers))

    async def _fetch_primary_email(self, headers: dict[str, str]) -> str | None:
        """Скрытый в настройках email лежит в отдельном ресурсе; его отсутствие не ошибка."""
        response = await self._client.get(f"{API_BASE_URL}/user/emails", headers=headers)
        if response.status_code != httpx.codes.OK:
            return None
        entries = _body(response, strict=False)
        if not isinstance(entries, list):
            return None
        return next(
            (
                email
                for entry in entries
                if isinstance(entry, dict)
                and entry.get("primary")
                and entry.get("verified")
                and (email := _text(entry.get("email")))
            ),
            None,
        )


def replace_email(profile: GitHubProfile, email: str | None) -> GitHubProfile:
    return GitHubProfile(
        provider_id=profile.provider_id,
        login=profile.login,
        name=profile.name,
        email=email,
        avatar_url=profile.avatar_url,
    )


def _parse_profile(payload: dict[str, object]) -> GitHubProfile:
    provider_id = payload.get("id")
    login = _text(payload.get("login"))
    if provider_id is None or login is None:
        raise OAuthProviderError("GitHub вернул профиль без id или login")
    return GitHubProfile(
        provider_id=str(provider_id),
        login=login,
        name=_text(payload.get("name")),
        email=_text(payload.get("email")),
        avatar_url=_text(payload.get("avatar_url")),
    )


def _body(response: httpx.Response, *, strict: bool = True) -> object:
    """Разбор ответа GitHub: чужой сервис, поэтому доверяем только проверенным полям."""
    if strict and response.status_code >= httpx.codes.BAD_REQUEST:
        logger.warning("github api error: %s %s", response.status_code, response.request.url)
        raise OAuthProviderError("GitHub ответил ошибкой")
    try:
        return response.json()
    except ValueError as exc:
        if strict:
            raise OAuthProviderError("GitHub вернул не JSON") from exc
        return None


def _as_object(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise OAuthProviderError("GitHub вернул неожиданную структуру ответа")
    return payload


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
