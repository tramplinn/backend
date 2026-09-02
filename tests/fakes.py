import uuid_utils.compat as uuid

from tramplin.models.enums import IdentityProvider, UserRole
from tramplin.models.users import RefreshToken, User, UserIdentity
from tramplin.services.contracts import OAuthProfile, OAuthState


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


class FakeUserRepository:
    def __init__(self) -> None:
        self.users: dict[uuid.UUID, User] = {}

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

    async def login_exists(self, login: str) -> bool:
        return any(user.login == login for user in self.users.values())

    def add(self, user: User) -> User:
        self.users[user.id] = user
        return user


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


class FakeStateStore:
    def __init__(self) -> None:
        self.states: dict[str, OAuthState] = {}

    async def issue(self, state: OAuthState) -> str:
        token = f"state-{len(self.states) + 1}"
        self.states[token] = state
        return token

    async def consume(self, token: str) -> OAuthState | None:
        return self.states.pop(token, None)
