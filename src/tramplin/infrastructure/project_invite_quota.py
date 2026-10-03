from datetime import UTC, datetime
from typing import Final

import uuid_utils.compat as uuid
from redis.asyncio import Redis

from tramplin.core.config import Settings
from tramplin.core.errors import TooManyRequestsError

NAMESPACE: Final = "projects:invites"
KEY_TTL_SECONDS: Final = 60 * 60 * 2


class ProjectInviteQuota:
    """Часовая корзина на пригласившего: приглашение рассылает письмо,
    и без лимита проект превращается в спам-рассылку от имени платформы."""

    def __init__(self, redis: Redis, settings: Settings) -> None:
        self._redis = redis
        self._limit = settings.project_invites_hourly_quota

    async def take(self, user_id: uuid.UUID) -> None:
        key = f"{NAMESPACE}:{datetime.now(UTC):%Y-%m-%dT%H}:{user_id}"
        used = await self._redis.incr(key)
        if used == 1:
            await self._redis.expire(key, KEY_TTL_SECONDS)
        if used > self._limit:
            raise TooManyRequestsError("Слишком много приглашений за час. Попробуйте позже.")
