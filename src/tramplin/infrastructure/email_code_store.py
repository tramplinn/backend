import json
import secrets
from typing import Final

from redis.asyncio import Redis

from tramplin.core.config import Settings
from tramplin.core.errors import InvalidEmailCodeError, TooManyRequestsError
from tramplin.infrastructure.redis_store import RedisNamespace
from tramplin.services.contracts import StatePurpose

CODE_NAMESPACE: Final = "email:otp"
COOLDOWN_NAMESPACE: Final = "email:otp:cooldown"
CODE_DIGITS: Final = 6


class EmailCodeStore:
    """Код живёт в Redis ограниченное время; счётчик попыток растёт и при
    неверном вводе — перебор кода не должен быть бесплатным (см. TutorQuota)."""

    def __init__(self, redis: Redis, settings: Settings) -> None:
        self._codes = RedisNamespace(redis, CODE_NAMESPACE, settings.email_code_ttl)
        self._cooldown = RedisNamespace(redis, COOLDOWN_NAMESPACE, settings.email_code_cooldown)
        self._max_attempts = settings.email_code_max_attempts

    async def issue(self, email: str, purpose: StatePurpose, *, scope: str | None = None) -> str:
        key = _key(email, purpose, scope)
        if await self._cooldown.get(key) is not None:
            raise TooManyRequestsError("Код уже отправлен — подождите перед повторной отправкой")
        code = f"{secrets.randbelow(10**CODE_DIGITS):0{CODE_DIGITS}d}"
        await self._codes.put(key, json.dumps({"code": code, "attempts": 0}))
        await self._cooldown.put(key, "1")
        return code

    async def verify(
        self, email: str, purpose: StatePurpose, code: str, *, scope: str | None = None
    ) -> None:
        key = _key(email, purpose, scope)
        raw = await self._codes.get(key)
        if raw is None:
            raise InvalidEmailCodeError("Код не найден или истёк — запросите новый")
        stored = json.loads(raw)
        if stored["attempts"] >= self._max_attempts:
            await self._codes.drop(key)
            raise InvalidEmailCodeError("Слишком много попыток — запросите новый код")
        if not secrets.compare_digest(stored["code"], code):
            stored["attempts"] += 1
            await self._codes.put(key, json.dumps(stored))
            raise InvalidEmailCodeError("Неверный код")
        await self._codes.drop(key)


def _key(email: str, purpose: StatePurpose, scope: str | None) -> str:
    """scope привязывает код к пользователю для link: тот, кто запросил, тот и подтверждает
    (как OAuthState.user_id в OAuth-привязке) — иначе код можно перехватить чужой сессией."""
    suffix = f":{scope}" if scope else ""
    return f"{purpose}:{email.strip().lower()}{suffix}"
