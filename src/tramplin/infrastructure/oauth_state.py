import json
from dataclasses import asdict

from redis.asyncio import Redis

from tramplin.core.config import Settings
from tramplin.core.security import generate_token
from tramplin.infrastructure.redis_store import RedisNamespace
from tramplin.models.enums import IdentityProvider
from tramplin.services.contracts import OAuthState

NAMESPACE = "oauth:state"


class OAuthStateStore:
    """State живёт в Redis ограниченное время и читается один раз."""

    def __init__(self, redis: Redis, settings: Settings) -> None:
        self._states = RedisNamespace(redis, NAMESPACE, settings.oauth_state_ttl)
        self._token_bytes = settings.oauth_state_bytes

    async def issue(self, state: OAuthState) -> str:
        token = generate_token(self._token_bytes)
        await self._states.put(token, json.dumps(asdict(state)))
        return token

    async def consume(self, token: str) -> OAuthState | None:
        raw = await self._states.take(token)
        if raw is None:
            return None
        payload = json.loads(raw)
        return OAuthState(
            provider=IdentityProvider(payload["provider"]),
            purpose=payload["purpose"],
            user_id=payload.get("user_id"),
            next_path=payload.get("next_path", "/"),
        )
