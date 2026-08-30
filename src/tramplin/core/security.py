import hashlib
import secrets
from datetime import datetime

import jwt
import uuid_utils.compat as uuid

from tramplin.core.config import Settings
from tramplin.core.errors import InvalidTokenError
from tramplin.core.time import utc_now


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def generate_token(nbytes: int) -> str:
    return secrets.token_urlsafe(nbytes)


def generate_refresh_token(nbytes: int) -> tuple[str, str]:
    """Сырое значение уходит в куку, в БД ложится только его хэш."""
    raw = generate_token(nbytes)
    return raw, sha256_hex(raw)


class AccessTokenCodec:
    def __init__(self, settings: Settings) -> None:
        self._secret = settings.jwt_secret.get_secret_value()
        self._algorithm = settings.jwt_algorithm
        self._issuer = settings.jwt_issuer
        self._ttl = settings.access_token_ttl

    def encode(self, user_id: uuid.UUID) -> tuple[str, datetime]:
        issued_at = utc_now()
        expires_at = issued_at + self._ttl
        token = jwt.encode(
            {
                "sub": str(user_id),
                "iss": self._issuer,
                "iat": int(issued_at.timestamp()),
                "exp": int(expires_at.timestamp()),
            },
            self._secret,
            algorithm=self._algorithm,
        )
        return token, expires_at

    def decode(self, token: str) -> uuid.UUID:
        """Роль в токен не кладём: права берём из свежей записи пользователя."""
        try:
            claims = jwt.decode(
                token,
                self._secret,
                algorithms=[self._algorithm],
                issuer=self._issuer,
                options={"require": ["sub", "exp", "iat", "iss"]},
            )
            return uuid.UUID(claims["sub"])
        except (jwt.PyJWTError, KeyError, ValueError) as exc:
            raise InvalidTokenError from exc
