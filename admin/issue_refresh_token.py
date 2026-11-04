"""Выдаёт refresh-токен пользователю и печатает его сырое значение.

Нужен e2e-тестам фронта (E2E_REFRESH_TOKEN): входа без OAuth/почты нет, а
токен — то, что браузер держит в куке после входа. Токен одноразовый, на
каждый прогон e2e выдаётся новый. Только для локального и тестового стенда.
"""

import asyncio
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tramplin.core.config import Settings, load_settings
from tramplin.core.security import generate_refresh_token
from tramplin.core.time import utc_now
from tramplin.models.users import RefreshToken, User


async def issue(settings: Settings, login: str) -> str | None:
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            user = await session.scalar(select(User).where(User.login == login))
            if user is None:
                return None
            raw, token_hash = generate_refresh_token(settings.refresh_token_bytes)
            session.add(
                RefreshToken(
                    user_id=user.id,
                    token_hash=token_hash,
                    expired_at=utc_now() + settings.refresh_token_ttl,
                )
            )
            await session.commit()
            return raw
    finally:
        await engine.dispose()


async def main() -> int:
    if len(sys.argv) != 2:
        print("usage: issue_refresh_token.py <login>", file=sys.stderr)  # noqa: T201
        return 2
    raw = await issue(load_settings(), sys.argv[1])
    if raw is None:
        print(f"пользователь {sys.argv[1]} не найден", file=sys.stderr)  # noqa: T201
        return 1
    print(raw)  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
