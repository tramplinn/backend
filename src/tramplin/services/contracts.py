from dataclasses import dataclass
from typing import Literal, Protocol

from tramplin.models.enums import IdentityProvider

StatePurpose = Literal["login", "link"]


class Transaction(Protocol):
    async def commit(self) -> None: ...


@dataclass(frozen=True, slots=True)
class PageResult[T]:
    items: list[T]
    total: int
    limit: int
    offset: int


@dataclass(frozen=True, slots=True)
class GitHubProfile:
    provider_id: str
    login: str
    name: str | None
    email: str | None
    avatar_url: str | None


@dataclass(frozen=True, slots=True)
class OAuthState:
    provider: IdentityProvider
    purpose: StatePurpose
    user_id: str | None = None
    next_path: str = "/"
