from datetime import timedelta

from redis.asyncio import Redis


class RedisNamespace:
    """Именованное пространство ключей: общий префикс и TTL, чтобы Redis не расползался."""

    def __init__(self, redis: Redis, prefix: str, ttl: timedelta) -> None:
        self._redis = redis
        self._prefix = prefix.rstrip(":")
        self._ttl = int(ttl.total_seconds())

    def key(self, key: str) -> str:
        return f"{self._prefix}:{key}"

    async def put(self, key: str, value: str, ttl: timedelta | None = None) -> None:
        seconds = int(ttl.total_seconds()) if ttl is not None else self._ttl
        await self._redis.set(self.key(key), value, ex=seconds)

    async def get(self, key: str) -> str | None:
        return _decode(await self._redis.get(self.key(key)))

    async def take(self, key: str) -> str | None:
        """Одноразовое чтение: значение сразу исчезает (GETDEL)."""
        return _decode(await self._redis.getdel(self.key(key)))

    async def drop(self, key: str) -> None:
        await self._redis.delete(self.key(key))


def _decode(value: str | bytes | None) -> str | None:
    """redis-py типизирует ответ как bytes | str независимо от decode_responses клиента."""
    return value.decode() if isinstance(value, bytes) else value
