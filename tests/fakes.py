from collections.abc import Sequence
from typing import Any

import uuid_utils.compat as uuid

from tramplin.core.errors import InvalidEmailCodeError, TooManyRequestsError
from tramplin.models.assets import Asset
from tramplin.models.directories import Company, Interest, University
from tramplin.models.enums import IdentityProvider, UserRole
from tramplin.models.notifications import EmailJobOutbox
from tramplin.models.users import RefreshToken, User, UserIdentity
from tramplin.services.contracts import (
    CourseActivity,
    OAuthProfile,
    OAuthState,
    ProfileStats,
    RenderedEmail,
    StatePurpose,
)

type CourseActivities = list[CourseActivity]


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1

    async def flush(self) -> None:
        pass


class FakeUserRepository:
    def __init__(self) -> None:
        self.users: dict[uuid.UUID, User] = {}
        self.stats = ProfileStats(0, 0, 0)
        self.courses: CourseActivities = []

    async def list(
        self,
        *,
        query: str | None,
        role: UserRole | None,
        is_active: bool | None,
        limit: int,
        offset: int,
    ) -> tuple[list[User], int]:
        users = list(self.users.values())
        if query:
            needle = query.casefold()
            users = [
                user
                for user in users
                if any(
                    needle in (value or "").casefold()
                    for value in (user.login, user.name, user.email, user.student_number)
                )
            ]
        if role is not None:
            users = [user for user in users if user.role == role]
        if is_active is not None:
            users = [user for user in users if user.is_active == is_active]
        return users[offset : offset + limit], len(users)

    async def get(self, user_id: uuid.UUID) -> User | None:
        return self.users.get(user_id)

    async def get_with_identities(self, user_id: uuid.UUID) -> User | None:
        return self.users.get(user_id)

    async def get_active_by_login(self, login: str) -> User | None:
        return next(
            (user for user in self.users.values() if user.login == login and user.is_active),
            None,
        )

    async def public_stats(self, user_id: uuid.UUID) -> ProfileStats:
        return self.stats

    async def active_courses(self, user_id: uuid.UUID) -> CourseActivities:
        return self.courses

    async def login_exists(self, login: str) -> bool:
        return any(user.login == login for user in self.users.values())

    def add(self, user: User) -> User:
        self.users[user.id] = user
        return user


class FakeCompanyRepository:
    def __init__(self) -> None:
        self.companies: dict[str, Company] = {}

    async def get_or_create_one(self, name: str) -> Company:
        clean = name.strip()
        key = clean.lower()
        if key not in self.companies:
            self.companies[key] = Company(name=clean)
        return self.companies[key]


class FakeUniversityRepository:
    def __init__(self) -> None:
        self.universities: dict[str, University] = {}

    async def get_or_create_one(self, name: str) -> University:
        clean = name.strip()
        key = clean.lower()
        if key not in self.universities:
            self.universities[key] = University(name=clean)
        return self.universities[key]


class FakeInterestRepository:
    def __init__(self) -> None:
        self.interests: dict[str, Interest] = {}

    async def get_or_create_many(self, names: Sequence[str]) -> list[Interest]:
        resolved: list[Interest] = []
        seen: set[str] = set()
        for raw in names:
            name = raw.strip()
            if not name or name.lower() in seen:
                continue
            seen.add(name.lower())
            key = name.lower()
            if key not in self.interests:
                self.interests[key] = Interest(name=name)
            resolved.append(self.interests[key])
        return resolved


class FakeAssetRepository:
    def __init__(self) -> None:
        self.assets: dict[uuid.UUID, Asset] = {}

    async def get(self, asset_id: uuid.UUID) -> Asset | None:
        return self.assets.get(asset_id)

    def add(self, asset: Asset) -> Asset:
        self.assets[asset.id] = asset
        return asset


class FakeIdentityRepository:
    def __init__(self, users: dict[uuid.UUID, User]) -> None:
        self.identities: list[UserIdentity] = []
        self._users = users

    async def get_by_provider(
        self,
        provider: IdentityProvider,
        provider_id: str,
    ) -> UserIdentity | None:
        for identity in self.identities:
            if identity.provider == provider and identity.provider_id == provider_id:
                identity.user = self._users[identity.user_id]
                return identity
        return None

    async def get_for_user(
        self,
        user_id: uuid.UUID,
        provider: IdentityProvider,
    ) -> UserIdentity | None:
        return next(
            (i for i in self.identities if i.user_id == user_id and i.provider == provider),
            None,
        )

    async def list_for_user(self, user_id: uuid.UUID) -> list[UserIdentity]:
        return [i for i in self.identities if i.user_id == user_id]

    def add(self, identity: UserIdentity) -> UserIdentity:
        self.identities.append(identity)
        return identity

    async def delete(self, identity: UserIdentity) -> None:
        self.identities.remove(identity)


class FakeRefreshTokenRepository:
    def __init__(self) -> None:
        self.tokens: list[RefreshToken] = []

    async def consume_by_hash(self, token_hash: str) -> RefreshToken | None:
        token = next((item for item in self.tokens if item.token_hash == token_hash), None)
        if token is not None:
            self.tokens.remove(token)
        return token

    def add(self, token: RefreshToken) -> RefreshToken:
        self.tokens.append(token)
        return token

    async def delete_for_user(self, user_id: uuid.UUID) -> int:
        before = len(self.tokens)
        self.tokens = [t for t in self.tokens if t.user_id != user_id]
        return before - len(self.tokens)


class FakeGitHubClient:
    def __init__(self, profile: OAuthProfile) -> None:
        self.profile = profile
        self.exchanged_codes: list[str] = []

    def authorize_url(self, state: str) -> str:
        return f"https://github.test/login/oauth/authorize?state={state}"

    async def exchange_code(self, code: str) -> str:
        self.exchanged_codes.append(code)
        return "gho_test_token"

    async def fetch_profile(self, access_token: str) -> OAuthProfile:
        return self.profile


class FakeEmailJobRepository:
    def __init__(self) -> None:
        self.jobs: list[EmailJobOutbox] = []

    def add(self, job: EmailJobOutbox) -> EmailJobOutbox:
        self.jobs.append(job)
        return job

    async def claim_outbox(self) -> EmailJobOutbox | None:
        return next((job for job in self.jobs if job.dispatched_at is None), None)


class FakeEmailCodeStore:
    """Код фиксирован ("000000"): тесты не гоняют secrets.randbelow, только контракт."""

    CODE = "000000"

    def __init__(self) -> None:
        self.issued: dict[str, str] = {}
        self.on_cooldown: set[str] = set()

    async def issue(self, email: str, purpose: StatePurpose, *, scope: str | None = None) -> str:
        key = f"{purpose}:{email}:{scope}"
        if key in self.on_cooldown:
            raise TooManyRequestsError("cooldown")
        self.issued[key] = self.CODE
        self.on_cooldown.add(key)
        return self.CODE

    async def verify(
        self, email: str, purpose: StatePurpose, code: str, *, scope: str | None = None
    ) -> None:
        key = f"{purpose}:{email}:{scope}"
        if self.issued.get(key) != code:
            raise InvalidEmailCodeError
        del self.issued[key]
        # Реальный cooldown в Redis живёт своим TTL и не снимается по verify — здесь
        # снимаем сразу, иначе тестам на повторный вход пришлось бы имитировать время.
        self.on_cooldown.discard(key)


class FakeEmailRenderer:
    def render(self, name: str, context: dict[str, Any]) -> RenderedEmail:
        return RenderedEmail(
            subject=f"subject:{name}:{context.get('code')}",
            html=f"<p>{context.get('code')}</p>",
            text=str(context.get("code")),
        )


class FakeStateStore:
    def __init__(self) -> None:
        self.states: dict[str, OAuthState] = {}

    async def issue(self, state: OAuthState) -> str:
        token = f"state-{len(self.states) + 1}"
        self.states[token] = state
        return token

    async def consume(self, token: str) -> OAuthState | None:
        return self.states.pop(token, None)
