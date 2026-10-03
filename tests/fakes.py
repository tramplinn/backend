from collections.abc import Sequence
from typing import Any

import uuid_utils.compat as uuid

from tramplin.core.errors import InvalidEmailCodeError, TooManyRequestsError
from tramplin.models.assets import Asset
from tramplin.models.directories import Company, Interest, University
from tramplin.models.enums import (
    IdentityProvider,
    ProjectInviteStatus,
    ProjectVisibility,
    UserRole,
)
from tramplin.models.notifications import EmailJobOutbox
from tramplin.models.projects import (
    Project,
    ProjectInvite,
    ProjectStatusEvent,
    UserProfileBlock,
)
from tramplin.models.users import RefreshToken, User, UserIdentity
from tramplin.services.contracts import (
    CourseActivity,
    OAuthProfile,
    OAuthState,
    ProfileStats,
    RenderedEmail,
    StatePurpose,
)
from tramplin.services.projects import ProjectCatalogFilters

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


class FakeProjectRepository:
    """In-memory проекты: фильтры каталога проверяются отдельно на уровне SQL."""

    def __init__(self) -> None:
        self.projects: dict[uuid.UUID, Project] = {}
        self.events: list[ProjectStatusEvent] = []
        self.catalog_calls: list[tuple[ProjectCatalogFilters, list[ProjectVisibility]]] = []

    async def catalog(
        self,
        filters: ProjectCatalogFilters,
        *,
        visibilities: Sequence[ProjectVisibility],
        limit: int,
        offset: int,
    ) -> tuple[list[Project], int]:
        self.catalog_calls.append((filters, list(visibilities)))
        items = [item for item in self.projects.values() if item.visibility in visibilities]
        return items[offset : offset + limit], len(items)

    async def list_for_member(self, user_id: uuid.UUID) -> list[Project]:
        return [
            project
            for project in self.projects.values()
            if any(member.user_id == user_id for member in project.members)
        ]

    async def get_by_slug(self, slug: str) -> Project | None:
        return next((item for item in self.projects.values() if item.slug == slug), None)

    async def slug_exists(self, slug: str) -> bool:
        return await self.get_by_slug(slug) is not None

    async def status_events(self, project_id: uuid.UUID) -> list[ProjectStatusEvent]:
        return [event for event in reversed(self.events) if event.project_id == project_id]

    async def next_profile_position(self, user_id: uuid.UUID) -> int:
        positions = [
            member.profile_position
            for project in self.projects.values()
            for member in project.members
            if member.user_id == user_id
        ]
        return max(positions, default=-1) + 1

    def add[T](self, entity: T) -> T:
        if isinstance(entity, Project):
            self.projects[entity.id] = entity
        elif isinstance(entity, ProjectStatusEvent):
            self.events.append(entity)
        return entity

    async def delete(self, entity: Project) -> None:
        self.projects.pop(entity.id, None)


class FakeProjectInviteRepository:
    def __init__(self) -> None:
        self.invites: dict[uuid.UUID, ProjectInvite] = {}

    async def get(self, invite_id: uuid.UUID) -> ProjectInvite | None:
        return self.invites.get(invite_id)

    async def list_pending_for_project(self, project_id: uuid.UUID) -> list[ProjectInvite]:
        return [item for item in self._pending() if item.project_id == project_id]

    async def list_pending_for_user(self, user_id: uuid.UUID) -> list[ProjectInvite]:
        return [item for item in self._pending() if item.invitee_id == user_id]

    async def find_pending(
        self,
        project_id: uuid.UUID,
        invitee_id: uuid.UUID,
    ) -> ProjectInvite | None:
        return next(
            (
                item
                for item in self._pending()
                if item.project_id == project_id and item.invitee_id == invitee_id
            ),
            None,
        )

    def add(self, invite: ProjectInvite) -> ProjectInvite:
        self.invites[invite.id] = invite
        return invite

    def _pending(self) -> list[ProjectInvite]:
        return [
            item for item in self.invites.values() if item.status is ProjectInviteStatus.PENDING
        ]


class FakeInviteQuota:
    def __init__(self, limit: int = 30) -> None:
        self.limit = limit
        self.taken: list[uuid.UUID] = []

    async def take(self, user_id: uuid.UUID) -> None:
        self.taken.append(user_id)
        if self.taken.count(user_id) > self.limit:
            raise TooManyRequestsError("quota")


class FakeProfileLayoutRepository:
    def __init__(self) -> None:
        self.rows: list[UserProfileBlock] = []

    async def list_for_user(self, user_id: uuid.UUID) -> list[UserProfileBlock]:
        return [row for row in self.rows if row.user_id == user_id]

    async def delete_for_user(self, user_id: uuid.UUID) -> None:
        self.rows = [row for row in self.rows if row.user_id != user_id]

    def add(self, block: UserProfileBlock) -> UserProfileBlock:
        self.rows.append(block)
        return block
