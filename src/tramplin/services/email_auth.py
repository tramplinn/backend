import re
from typing import Any, Final, Protocol

import uuid_utils.compat as uuid

from tramplin.core.config import Settings
from tramplin.models.enums import EmailQueue, IdentityProvider
from tramplin.models.notifications import EmailJobOutbox
from tramplin.models.users import User
from tramplin.services.contracts import OAuthProfile, RenderedEmail, StatePurpose, Transaction
from tramplin.services.identity_linking import IdentityLinker
from tramplin.services.notifications import EmailJobRepositoryPort
from tramplin.services.oauth_auth import AuthResult
from tramplin.services.session import SessionService
from tramplin.services.users import UserIdentityRepositoryPort, UserRepositoryPort

LOCAL_PART_FORBIDDEN: Final = re.compile(r"[^a-z0-9._-]+")


class EmailCodeStorePort(Protocol):
    async def issue(
        self, email: str, purpose: StatePurpose, *, scope: str | None = None
    ) -> str: ...

    async def verify(
        self, email: str, purpose: StatePurpose, code: str, *, scope: str | None = None
    ) -> None: ...


class EmailRendererPort(Protocol):
    def render(self, name: str, context: dict[str, Any]) -> RenderedEmail: ...


class EmailAuthService:
    """Тот же вход, что у OAuth (регистрация/привязка через IdentityLinker), только
    без редиректа: код подтверждает владение почтой вместо согласия провайдера."""

    def __init__(
        self,
        session: Transaction,
        users: UserRepositoryPort,
        identities: UserIdentityRepositoryPort,
        jobs: EmailJobRepositoryPort,
        codes: EmailCodeStorePort,
        renderer: EmailRendererPort,
        sessions: SessionService,
        settings: Settings,
    ) -> None:
        self._session = session
        self._linker = IdentityLinker(users, identities)
        self._jobs = jobs
        self._codes = codes
        self._renderer = renderer
        self._sessions = sessions
        self._settings = settings

    async def request_login_code(self, email: str) -> None:
        await self._send_code(email, "login", scope=None)

    async def verify_login_code(self, email: str, code: str) -> AuthResult:
        normalized = _normalize(email)
        await self._codes.verify(normalized, "login", code, scope=None)
        user = await self._linker.login_or_register(IdentityProvider.EMAIL, _profile(normalized))
        tokens = self._sessions.issue(user)
        await self._session.commit()
        return AuthResult(user=user, tokens=tokens, next_path="/")

    async def request_link_code(self, user_id: uuid.UUID, email: str) -> None:
        """Код привязан к user_id, запросившему его: подтвердить может только он же."""
        await self._send_code(email, "link", scope=str(user_id))

    async def verify_link_code(self, user_id: uuid.UUID, email: str, code: str) -> User:
        normalized = _normalize(email)
        await self._codes.verify(normalized, "link", code, scope=str(user_id))
        user = await self._linker.link_identity(
            IdentityProvider.EMAIL, user_id, _profile(normalized)
        )
        await self._session.commit()
        return user

    async def _send_code(self, email: str, purpose: StatePurpose, *, scope: str | None) -> None:
        normalized = _normalize(email)
        code = await self._codes.issue(normalized, purpose, scope=scope)
        ttl_minutes = int(self._settings.email_code_ttl.total_seconds() // 60)
        rendered = self._renderer.render("otp", {"code": code, "ttl_minutes": ttl_minutes})
        self._jobs.add(
            EmailJobOutbox(
                to_email=normalized,
                subject=rendered.subject,
                html_body=rendered.html,
                text_body=rendered.text,
                category="auth_otp",
                queue=EmailQueue.TRANSACTIONAL,
                dispatched_at=None,
                attempts=0,
                last_error=None,
            ),
        )
        await self._session.commit()


def _normalize(email: str) -> str:
    return email.strip().lower()


def _profile(normalized_email: str) -> OAuthProfile:
    local_part = normalized_email.split("@", 1)[0]
    login = LOCAL_PART_FORBIDDEN.sub("-", local_part).strip("-") or "student"
    return OAuthProfile(
        provider_id=normalized_email,
        login=login,
        name=None,
        email=normalized_email,
        avatar_url=None,
    )
