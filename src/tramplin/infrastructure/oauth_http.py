"""Разбор ответов OAuth-провайдеров: чужой сервис, доверяем только проверенным полям."""

import logging
from typing import Final

import httpx

from tramplin.core.errors import OAuthProviderError

logger = logging.getLogger(__name__)

TIMEOUT_NOTE: Final = "ответил ошибкой"


def body(response: httpx.Response, provider: str, *, strict: bool = True) -> object:
    if strict and response.status_code >= httpx.codes.BAD_REQUEST:
        logger.warning(
            "%s api error: %s %s",
            provider.lower(),
            response.status_code,
            response.request.url,
        )
        raise OAuthProviderError(f"{provider} {TIMEOUT_NOTE}")
    try:
        return response.json()
    except ValueError as exc:
        if strict:
            raise OAuthProviderError(f"{provider} вернул не JSON") from exc
        return None


def as_object(payload: object, provider: str) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise OAuthProviderError(f"{provider} вернул неожиданную структуру ответа")
    return payload


def text(value: object) -> str | None:
    """Пустая строка от провайдера означает «поля нет», а не пустое значение."""
    return value if isinstance(value, str) and value else None
