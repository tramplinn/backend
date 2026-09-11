from typing import Any, cast

import pytest
from pydantic import SecretStr

from tests.conftest import TEST_SECRET
from tramplin.core.config import Settings
from tramplin.core.errors import InvalidEmailCodeError, TooManyRequestsError
from tramplin.infrastructure.email_code_store import EmailCodeStore


class FakeRedis:
    """В отличие от AsyncMock-фейка в test_infrastructure_adapters — реально хранит
    состояние между вызовами: cooldown и счётчик попыток нельзя проверить без этого."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.store[key] = value

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def getdel(self, key: str) -> str | None:
        return self.store.pop(key, None)

    async def delete(self, key: str) -> None:
        self.store.pop(key, None)


@pytest.fixture
def store() -> EmailCodeStore:
    settings = Settings(
        _env_file=None,
        jwt_secret=TEST_SECRET,
        github_client_id="cid",
        github_client_secret=SecretStr("csecret"),
        email_code_max_attempts=3,
    )
    return EmailCodeStore(cast(Any, FakeRedis()), settings)


async def test_issue_then_verify_succeeds(store: EmailCodeStore) -> None:
    code = await store.issue("student@example.com", "login")
    assert len(code) == 6

    await store.verify("student@example.com", "login", code)


async def test_verify_is_one_time_use(store: EmailCodeStore) -> None:
    code = await store.issue("student@example.com", "login")
    await store.verify("student@example.com", "login", code)

    with pytest.raises(InvalidEmailCodeError, match="не найден"):
        await store.verify("student@example.com", "login", code)


async def test_verify_rejects_wrong_code_and_counts_attempts(store: EmailCodeStore) -> None:
    await store.issue("student@example.com", "login")

    for _ in range(3):
        with pytest.raises(InvalidEmailCodeError, match="Неверный код"):
            await store.verify("student@example.com", "login", "000000")
    with pytest.raises(InvalidEmailCodeError, match="попыток"):
        await store.verify("student@example.com", "login", "000000")


async def test_issue_respects_cooldown(store: EmailCodeStore) -> None:
    await store.issue("student@example.com", "login")

    with pytest.raises(TooManyRequestsError):
        await store.issue("student@example.com", "login")


async def test_login_and_link_purposes_are_independent(store: EmailCodeStore) -> None:
    login_code = await store.issue("student@example.com", "login")
    link_code = await store.issue("student@example.com", "link")

    with pytest.raises(InvalidEmailCodeError):
        await store.verify("student@example.com", "login", link_code)
    await store.verify("student@example.com", "login", login_code)


async def test_link_scope_isolates_different_users(store: EmailCodeStore) -> None:
    code = await store.issue("student@example.com", "link", scope="user-a")

    with pytest.raises(InvalidEmailCodeError):
        await store.verify("student@example.com", "link", code, scope="user-b")
    await store.verify("student@example.com", "link", code, scope="user-a")


async def test_email_is_case_and_whitespace_insensitive(store: EmailCodeStore) -> None:
    code = await store.issue(" Student@Example.com ", "login")
    await store.verify("student@example.com", "login", code)
