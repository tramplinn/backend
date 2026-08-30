from datetime import UTC, datetime
from typing import Final

import uuid_utils.compat as uuid
from redis.asyncio import Redis

from tramplin.core.config import Settings
from tramplin.core.errors import TooManyRequestsError

NAMESPACE: Final = "tutor:quota"
KEY_TTL_SECONDS: Final = 60 * 60 * 26


class TutorQuota:
    """Счётчик растёт и при отказе: перебор запросов не должен быть бесплатным."""

    def __init__(self, redis: Redis, settings: Settings) -> None:
        self._redis = redis
        self._settings = settings

    async def take_user(self, user_id: uuid.UUID) -> None:
        await self._take(
            "user",
            str(user_id),
            self._settings.llm_daily_quota,
            "На сегодня вопросы к ассистенту закончились. Лимит обновится завтра.",
        )

    async def take_guest(self, guest_id: str, ip: str | None) -> None:
        """
        Три корзины по возрастанию охвата: браузер, адрес, все гости вместе.
        Первые две обходятся стиранием куки и сменой адреса, границу расходов
        держит третья.
        """
        await self._take(
            "guest",
            guest_id,
            self._settings.llm_guest_quota,
            "Бесплатные вопросы закончились. Войдите — их станет больше.",
        )
        if ip:
            await self._take(
                "ip",
                ip,
                self._settings.llm_guest_ip_quota,
                "С этого адреса сегодня задали слишком много вопросов. Войдите, чтобы продолжить.",
            )
        await self._take(
            "guests",
            "all",
            self._settings.llm_guest_daily_total,
            "Бесплатные вопросы на сегодня разобрали. Войдите, чтобы продолжить.",
        )

    async def _take(self, scope: str, subject: str, limit: int, refusal: str) -> None:
        key = f"{NAMESPACE}:{scope}:{datetime.now(UTC):%Y-%m-%d}:{subject}"
        used = await self._redis.incr(key)
        if used == 1:
            await self._redis.expire(key, KEY_TTL_SECONDS)
        if used > limit:
            raise TooManyRequestsError(refusal)
