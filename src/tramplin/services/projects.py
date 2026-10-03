import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from typing import Any, Final, Literal, Protocol

import uuid_utils.compat as uuid

from tramplin.core.config import Settings
from tramplin.core.errors import ConflictError, ForbiddenError, InvalidUpdateError, NotFoundError
from tramplin.core.time import utc_now
from tramplin.models.enums import (
    EmailQueue,
    ProjectInviteStatus,
    ProjectLinkKind,
    ProjectRole,
    ProjectStatus,
    ProjectVisibility,
    UserRole,
)
from tramplin.models.notifications import EmailJobOutbox
from tramplin.models.projects import (
    Project,
    ProjectInvite,
    ProjectLink,
    ProjectMember,
    ProjectStatusEvent,
)
from tramplin.models.users import User
from tramplin.services.assets import AssetRepositoryPort, resolve_image_asset
from tramplin.services.contracts import PageResult, RenderedEmail, Transaction
from tramplin.services.entity_updates import (
    mark_created,
    mark_updated,
    require,
    validate_required_updates,
)

ProjectSort = Literal["updated", "created", "status_changed", "title"]
type Projects = list[Project]
type Invites = list[ProjectInvite]

INVITE_TTL: Final = timedelta(days=14)
SLUG_MAX_LENGTH: Final = 80
SLUG_FALLBACK: Final = "project"
INVITE_EMAIL_CATEGORY: Final = "project_invite"

ROLE_RANK: Final[dict[ProjectRole, int]] = {
    ProjectRole.VIEWER: 0,
    ProjectRole.CONTRIBUTOR: 1,
    ProjectRole.MAINTAINER: 2,
    ProjectRole.OWNER: 3,
}
ROLE_LABELS: Final[dict[ProjectRole, str]] = {
    ProjectRole.OWNER: "владелец",
    ProjectRole.MAINTAINER: "мейнтейнер",
    ProjectRole.CONTRIBUTOR: "участник",
    ProjectRole.VIEWER: "наблюдатель",
}


class ProjectAction(StrEnum):
    VIEW = "view"
    EDIT_CONTENT = "edit_content"
    MANAGE_LINKS = "manage_links"
    CHANGE_STATUS = "change_status"
    EDIT_SETTINGS = "edit_settings"
    MANAGE_MEMBERS = "manage_members"
    CHANGE_ROLES = "change_roles"
    TRANSFER = "transfer"
    DELETE = "delete"


# Матрица §4.3 спецификации: минимальная роль для каждого действия.
ACTION_MIN_ROLE: Final[dict[ProjectAction, ProjectRole]] = {
    ProjectAction.VIEW: ProjectRole.VIEWER,
    ProjectAction.EDIT_CONTENT: ProjectRole.CONTRIBUTOR,
    ProjectAction.MANAGE_LINKS: ProjectRole.CONTRIBUTOR,
    ProjectAction.CHANGE_STATUS: ProjectRole.MAINTAINER,
    ProjectAction.EDIT_SETTINGS: ProjectRole.MAINTAINER,
    ProjectAction.MANAGE_MEMBERS: ProjectRole.MAINTAINER,
    ProjectAction.CHANGE_ROLES: ProjectRole.OWNER,
    ProjectAction.TRANSFER: ProjectRole.OWNER,
    ProjectAction.DELETE: ProjectRole.OWNER,
}
SETTINGS_FIELDS: Final = frozenset({"title", "slug", "visibility"})

TRANSLIT: Final = str.maketrans(
    {
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
        "ж": "zh", "з": "z", "и": "i", "й": "i", "к": "k", "л": "l", "м": "m",
        "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
        "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "",
        "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    }
)  # fmt: skip


def slugify(value: str) -> str:
    """Та же транслитерация, что и в lib/slug.ts фронтенда."""
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower().translate(TRANSLIT)).strip("-")
    return slug[:SLUG_MAX_LENGTH].strip("-") or SLUG_FALLBACK


def member_of(project: Project, user_id: uuid.UUID) -> ProjectMember | None:
    return next((item for item in project.members if item.user_id == user_id), None)


def role_of(project: Project, user: User | None) -> ProjectRole | None:
    """Роль зрителя в проекте; админ платформы действует с правами владельца."""
    if user is None:
        return None
    if user.role is UserRole.ADMIN:
        return ProjectRole.OWNER
    member = member_of(project, user.id)
    return member.role if member else None


def can_view(project: Project, user: User | None) -> bool:
    if project.visibility is ProjectVisibility.PUBLIC:
        return True
    if project.visibility is ProjectVisibility.AUTHENTICATED:
        return user is not None
    return role_of(project, user) is not None


def ensure_can(project: Project, user: User | None, action: ProjectAction) -> ProjectRole | None:
    """Единая точка проверки прав. Невидимый проект — 404, а не 403:
    не раскрываем сам факт его существования."""
    if not can_view(project, user):
        raise NotFoundError("Проект не найден")
    role = role_of(project, user)
    if action is ProjectAction.VIEW:
        return role
    if role is None or ROLE_RANK[role] < ROLE_RANK[ACTION_MIN_ROLE[action]]:
        raise ForbiddenError("Недостаточно прав в проекте")
    return role


def ensure_not_archived(project: Project) -> None:
    if project.status is ProjectStatus.ARCHIVED:
        raise ConflictError("Проект в архиве: чтобы править его, сначала смените статус")


@dataclass(frozen=True, slots=True)
class ProjectCatalogFilters:
    query: str | None = None
    statuses: Sequence[ProjectStatus] = ()
    link_kinds: Sequence[ProjectLinkKind] = ()
    member_login: str | None = None
    sort: ProjectSort = "updated"


@dataclass(frozen=True, slots=True)
class ProjectLinkInput:
    kind: ProjectLinkKind
    url: str
    label: str | None = None


@dataclass(frozen=True, slots=True)
class ProfileProjectOrder:
    project_id: uuid.UUID
    show_in_profile: bool


@dataclass(slots=True)
class ProjectView:
    """Проект глазами конкретного зрителя: его роль решает, что можно показать."""

    project: Project
    viewer_role: ProjectRole | None
    member: ProjectMember | None = None


class ProjectRepositoryPort(Protocol):
    async def catalog(
        self,
        filters: ProjectCatalogFilters,
        *,
        visibilities: Sequence[ProjectVisibility],
        limit: int,
        offset: int,
    ) -> tuple[list[Project], int]: ...

    async def list_for_member(self, user_id: uuid.UUID) -> list[Project]: ...

    async def get_by_slug(self, slug: str) -> Project | None: ...

    async def slug_exists(self, slug: str) -> bool: ...

    async def status_events(self, project_id: uuid.UUID) -> list[ProjectStatusEvent]: ...

    async def next_profile_position(self, user_id: uuid.UUID) -> int: ...

    def add[T](self, entity: T) -> T: ...

    async def delete(self, entity: Project) -> None: ...


class ProjectInviteRepositoryPort(Protocol):
    async def get(self, invite_id: uuid.UUID) -> ProjectInvite | None: ...

    async def list_pending_for_project(self, project_id: uuid.UUID) -> list[ProjectInvite]: ...

    async def list_pending_for_user(self, user_id: uuid.UUID) -> list[ProjectInvite]: ...

    async def find_pending(
        self,
        project_id: uuid.UUID,
        invitee_id: uuid.UUID,
    ) -> ProjectInvite | None: ...

    def add(self, invite: ProjectInvite) -> ProjectInvite: ...


class ProjectUserLookupPort(Protocol):
    async def get_active_by_login(self, login: str) -> User | None: ...


class EmailJobWriterPort(Protocol):
    def add(self, job: EmailJobOutbox) -> EmailJobOutbox: ...


class EmailRendererPort(Protocol):
    def render(self, name: str, context: dict[str, Any]) -> RenderedEmail: ...


class InviteQuotaPort(Protocol):
    async def take(self, user_id: uuid.UUID) -> None: ...


class ProjectService:
    def __init__(
        self,
        transaction: Transaction,
        projects: ProjectRepositoryPort,
        invites: ProjectInviteRepositoryPort,
        users: ProjectUserLookupPort,
        assets: AssetRepositoryPort,
        email_jobs: EmailJobWriterPort,
        renderer: EmailRendererPort,
        quota: InviteQuotaPort,
        settings: Settings,
    ) -> None:
        self._transaction = transaction
        self._projects = projects
        self._invites = invites
        self._users = users
        self._assets = assets
        self._email_jobs = email_jobs
        self._renderer = renderer
        self._quota = quota
        self._settings = settings

    # --- Чтение ---------------------------------------------------------------

    async def catalog(
        self,
        viewer: User | None,
        filters: ProjectCatalogFilters,
        *,
        limit: int = 24,
        offset: int = 0,
    ) -> PageResult[ProjectView]:
        """private не попадает в каталог даже участникам: для них есть /me/projects."""
        visibilities = [ProjectVisibility.PUBLIC]
        if viewer is not None:
            visibilities.append(ProjectVisibility.AUTHENTICATED)
        items, total = await self._projects.catalog(
            filters, visibilities=visibilities, limit=limit, offset=offset
        )
        return PageResult(
            items=[self._view(item, viewer) for item in items],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def list_mine(self, user: User) -> list[ProjectView]:
        projects = await self._projects.list_for_member(user.id)
        views = [self._view(item, user, member_id=user.id) for item in projects]
        return sorted(views, key=lambda view: view.member.profile_position if view.member else 0)

    async def list_for_profile(self, owner: User, viewer: User | None) -> list[ProjectView]:
        projects = await self._projects.list_for_member(owner.id)
        views = [
            self._view(project, viewer, member_id=owner.id)
            for project in projects
            if can_view(project, viewer)
        ]
        shown = [view for view in views if view.member is not None and view.member.show_in_profile]
        return sorted(shown, key=lambda view: view.member.profile_position if view.member else 0)

    async def get(self, slug: str, viewer: User | None) -> ProjectView:
        project = await self._load(slug)
        ensure_can(project, viewer, ProjectAction.VIEW)
        return self._view(project, viewer)

    async def status_events(self, slug: str, viewer: User | None) -> list[ProjectStatusEvent]:
        project = await self._load(slug)
        ensure_can(project, viewer, ProjectAction.VIEW)
        return await self._projects.status_events(project.id)

    # --- Проект ---------------------------------------------------------------

    async def create(
        self,
        actor: User,
        *,
        title: str,
        summary: str | None = None,
        visibility: ProjectVisibility = ProjectVisibility.PRIVATE,
    ) -> ProjectView:
        now = utc_now()
        project = Project(
            slug=await self._free_slug(slugify(title)),
            title=title.strip(),
            summary=summary,
            readme_md="",
            status=ProjectStatus.IDEA,
            visibility=visibility,
            status_changed_at=now,
        )
        # Сессия живёт с expire_on_commit=False: серверные умолчания после INSERT не
        # подгружаются, а ответ их показывает — проставляем время сами.
        project.created_at = project.updated_at = now
        mark_created(project, actor.id)
        owner = ProjectMember(
            project_id=project.id,
            user_id=actor.id,
            role=ProjectRole.OWNER,
            show_in_profile=True,
            profile_position=await self._projects.next_profile_position(actor.id),
            joined_at=now,
        )
        owner.user = actor
        mark_created(owner, actor.id)
        project.members = [owner]
        project.links = []
        self._projects.add(project)
        self._record_status(project, None, ProjectStatus.IDEA, actor)
        await self._transaction.commit()
        return self._view(project, actor)

    async def update(self, slug: str, actor: User, changes: dict[str, Any]) -> ProjectView:
        project = await self._load(slug)
        # Права проверяются по полям: README правит contributor, адрес и видимость —
        # только maintainer+. Пустой PATCH требует хотя бы права на содержимое.
        ensure_can(project, actor, ProjectAction.EDIT_CONTENT)
        if changes.keys() & SETTINGS_FIELDS:
            ensure_can(project, actor, ProjectAction.EDIT_SETTINGS)
        ensure_not_archived(project)
        validate_required_updates(changes, {"title", "slug", "visibility", "readme_md"})

        if "slug" in changes and changes["slug"] != project.slug:
            if await self._projects.slug_exists(changes["slug"]):
                raise ConflictError("Проект с таким адресом уже существует", field="slug")
            project.slug = changes["slug"]
        if "title" in changes:
            project.title = changes["title"].strip()
        if "visibility" in changes:
            project.visibility = changes["visibility"]
        if "summary" in changes:
            project.summary = changes["summary"]
        if "readme_md" in changes:
            project.readme_md = changes["readme_md"]
        if "logo_asset_id" in changes:
            logo = await resolve_image_asset(
                self._assets, changes["logo_asset_id"], owner="проекта"
            )
            project.logo_asset = logo
            project.logo_asset_id = logo.id if logo else None
        mark_updated(project, actor.id)
        project.updated_at = utc_now()
        await self._transaction.commit()
        return self._view(project, actor)

    async def change_status(self, slug: str, actor: User, status: ProjectStatus) -> ProjectView:
        project = await self._load(slug)
        ensure_can(project, actor, ProjectAction.CHANGE_STATUS)
        if project.status is not status:
            self._record_status(project, project.status, status, actor)
            project.status = status
            project.status_changed_at = utc_now()
            project.updated_at = project.status_changed_at
            mark_updated(project, actor.id)
            await self._transaction.commit()
        return self._view(project, actor)

    async def delete(self, slug: str, actor: User) -> None:
        project = await self._load(slug)
        ensure_can(project, actor, ProjectAction.DELETE)
        await self._projects.delete(project)
        await self._transaction.commit()

    async def replace_links(
        self,
        slug: str,
        actor: User,
        links: Sequence[ProjectLinkInput],
    ) -> ProjectView:
        """Список целиком: порядок ссылок — это порядок массива."""
        project = await self._load(slug)
        ensure_can(project, actor, ProjectAction.MANAGE_LINKS)
        ensure_not_archived(project)
        replaced: list[ProjectLink] = []
        for position, item in enumerate(links):
            link = ProjectLink(
                project_id=project.id,
                kind=item.kind,
                url=item.url,
                label=item.label,
                position=position,
            )
            mark_created(link, actor.id)
            replaced.append(link)
        project.links = replaced
        mark_updated(project, actor.id)
        project.updated_at = utc_now()
        await self._transaction.commit()
        return self._view(project, actor)

    # --- Участники ------------------------------------------------------------

    async def members(self, slug: str, viewer: User | None) -> ProjectView:
        return await self.get(slug, viewer)

    async def update_member(
        self,
        slug: str,
        actor: User,
        login: str,
        changes: dict[str, Any],
    ) -> ProjectMember:
        """Свою подпись меняет любой участник, чужую — maintainer+, роль — только владелец."""
        project = await self._load(slug)
        ensure_can(project, actor, ProjectAction.VIEW)
        target = self._member_by_login(project, login)
        if target.user_id != actor.id:
            ensure_can(project, actor, ProjectAction.MANAGE_MEMBERS)
        if "role" in changes:
            ensure_can(project, actor, ProjectAction.CHANGE_ROLES)
            new_role = changes["role"]
            if new_role is None:
                raise InvalidUpdateError("Поле role не может быть null", field="role")
            if new_role is ProjectRole.OWNER or target.role is ProjectRole.OWNER:
                raise ConflictError("Владелец меняется только передачей владения")
            target.role = new_role
        if "title" in changes:
            target.title = changes["title"]
        mark_updated(target, actor.id)
        await self._transaction.commit()
        return target

    async def remove_member(self, slug: str, actor: User, login: str) -> None:
        """Себя может убрать любой, кроме владельца; других — только с ролью ниже своей."""
        project = await self._load(slug)
        ensure_can(project, actor, ProjectAction.VIEW)
        target = self._member_by_login(project, login)
        if target.role is ProjectRole.OWNER:
            raise ConflictError("Владелец не может покинуть проект, не передав владение")
        if target.user_id != actor.id:
            role = require(
                ensure_can(project, actor, ProjectAction.MANAGE_MEMBERS),
                ForbiddenError("Недостаточно прав в проекте"),
            )
            if ROLE_RANK[target.role] >= ROLE_RANK[role]:
                raise ForbiddenError("Исключать можно только участников с ролью ниже своей")
        project.members.remove(target)
        await self._transaction.commit()

    async def transfer(self, slug: str, actor: User, login: str) -> ProjectView:
        project = await self._load(slug)
        ensure_can(project, actor, ProjectAction.TRANSFER)
        target = self._member_by_login(project, login)
        if target.role is ProjectRole.OWNER:
            raise ConflictError("Этот участник уже владелец проекта")
        if not target.user.is_active:
            raise ConflictError("Нельзя передать владение отключённому пользователю")
        previous = next(item for item in project.members if item.role is ProjectRole.OWNER)
        previous.role = ProjectRole.MAINTAINER
        mark_updated(previous, actor.id)
        # Частичный уникальный индекс на владельца проверяется сразу, а не в конце
        # транзакции: прежний владелец должен уйти в maintainer до повышения нового.
        await self._transaction.flush()
        target.role = ProjectRole.OWNER
        mark_updated(target, actor.id)
        await self._transaction.commit()
        return self._view(project, actor)

    # --- Приглашения ----------------------------------------------------------

    async def project_invites(self, slug: str, actor: User) -> Invites:
        project = await self._load(slug)
        ensure_can(project, actor, ProjectAction.MANAGE_MEMBERS)
        return await self._fresh(await self._invites.list_pending_for_project(project.id))

    async def invite(
        self,
        slug: str,
        actor: User,
        *,
        login: str,
        role: ProjectRole,
        title: str | None = None,
    ) -> ProjectInvite:
        project = await self._load(slug)
        actor_role = require(
            ensure_can(project, actor, ProjectAction.MANAGE_MEMBERS),
            ForbiddenError("Недостаточно прав в проекте"),
        )
        ensure_not_archived(project)
        if role is ProjectRole.OWNER:
            raise InvalidUpdateError("Владельца нельзя пригласить — только передать владение")
        if ROLE_RANK[role] >= ROLE_RANK[actor_role]:
            raise ForbiddenError("Приглашать можно только на роль ниже своей")
        invitee = await self._users.get_active_by_login(login)
        if invitee is None or not invitee.is_active:
            raise NotFoundError("Пользователь не найден")
        if invitee.id == actor.id:
            raise ConflictError("Нельзя пригласить самого себя")
        if member_of(project, invitee.id) is not None:
            raise ConflictError("Пользователь уже участвует в проекте")
        pending = await self._fresh(
            [item for item in [await self._invites.find_pending(project.id, invitee.id)] if item]
        )
        if pending:
            raise ConflictError("Приглашение этому пользователю уже отправлено")
        await self._quota.take(actor.id)

        now = utc_now()
        invite = ProjectInvite(
            project_id=project.id,
            invitee_id=invitee.id,
            inviter_id=actor.id,
            role=role,
            title=title,
            status=ProjectInviteStatus.PENDING,
            expires_at=now + INVITE_TTL,
            responded_at=None,
        )
        invite.created_at = now
        invite.project = project
        invite.invitee = invitee
        invite.inviter = actor
        mark_created(invite, actor.id)
        self._invites.add(invite)
        if invitee.email:
            self._send_invite_email(invite, project, actor, invitee.email)
        await self._transaction.commit()
        return invite

    async def revoke_invite(self, slug: str, actor: User, invite_id: uuid.UUID) -> None:
        project = await self._load(slug)
        ensure_can(project, actor, ProjectAction.MANAGE_MEMBERS)
        invite = await self._invites.get(invite_id)
        if invite is None or invite.project_id != project.id:
            raise NotFoundError("Приглашение не найдено")
        if invite.status is not ProjectInviteStatus.PENDING:
            raise ConflictError("Приглашение уже неактивно")
        invite.status = ProjectInviteStatus.REVOKED
        invite.responded_at = utc_now()
        mark_updated(invite, actor.id)
        await self._transaction.commit()

    async def my_invites(self, user: User) -> Invites:
        return await self._fresh(await self._invites.list_pending_for_user(user.id))

    async def accept_invite(self, user: User, invite_id: uuid.UUID) -> ProjectView:
        invite = await self._own_pending_invite(user, invite_id)
        project = invite.project
        invite.status = ProjectInviteStatus.ACCEPTED
        invite.responded_at = utc_now()
        mark_updated(invite, user.id)
        if member_of(project, user.id) is None:
            member = ProjectMember(
                project_id=project.id,
                user_id=user.id,
                role=invite.role,
                title=invite.title,
                show_in_profile=True,
                profile_position=await self._projects.next_profile_position(user.id),
                joined_at=invite.responded_at,
            )
            member.user = user
            mark_created(member, user.id)
            project.members.append(member)
        await self._transaction.commit()
        return self._view(project, user)

    async def decline_invite(self, user: User, invite_id: uuid.UUID) -> None:
        invite = await self._own_pending_invite(user, invite_id)
        invite.status = ProjectInviteStatus.DECLINED
        invite.responded_at = utc_now()
        mark_updated(invite, user.id)
        await self._transaction.commit()

    # --- Профиль --------------------------------------------------------------

    async def reorder_profile(self, user: User, items: Sequence[ProfileProjectOrder]) -> None:
        """Порядок задаётся целиком, как и везде с position: частичный список молча
        оставил бы дыры в нумерации."""
        projects = await self._projects.list_for_member(user.id)
        members = {
            member.project_id: member
            for project in projects
            if (member := member_of(project, user.id)) is not None
        }
        requested = [item.project_id for item in items]
        if len(requested) != len(set(requested)) or set(requested) != set(members):
            raise ConflictError(
                "Порядок должен содержать все ваши проекты ровно один раз",
                missing=[str(item) for item in set(members) - set(requested)],
                unknown=[str(item) for item in set(requested) - set(members)],
            )
        for position, item in enumerate(items):
            member = members[item.project_id]
            member.profile_position = position
            member.show_in_profile = item.show_in_profile
            mark_updated(member, user.id)
        await self._transaction.commit()

    # --- Внутреннее -----------------------------------------------------------

    async def _load(self, slug: str) -> Project:
        return require(await self._projects.get_by_slug(slug), NotFoundError("Проект не найден"))

    def _view(
        self,
        project: Project,
        viewer: User | None,
        *,
        member_id: uuid.UUID | None = None,
    ) -> ProjectView:
        return ProjectView(
            project=project,
            viewer_role=role_of(project, viewer),
            member=member_of(project, member_id) if member_id is not None else None,
        )

    def _member_by_login(self, project: Project, login: str) -> ProjectMember:
        return require(
            next((item for item in project.members if item.user.login == login), None),
            NotFoundError("Участник не найден"),
        )

    async def _free_slug(self, base: str) -> str:
        candidate, suffix = base, 1
        while await self._projects.slug_exists(candidate):
            suffix += 1
            tail = f"-{suffix}"
            candidate = f"{base[: SLUG_MAX_LENGTH - len(tail)].rstrip('-')}{tail}"
        return candidate

    def _record_status(
        self,
        project: Project,
        from_status: ProjectStatus | None,
        to_status: ProjectStatus,
        actor: User,
    ) -> None:
        event = ProjectStatusEvent(
            project_id=project.id,
            from_status=from_status,
            to_status=to_status,
            actor_id=actor.id,
        )
        event.actor = actor
        event.created_at = event.updated_at = utc_now()
        mark_created(event, actor.id)
        self._projects.add(event)

    async def _fresh(self, invites: Invites) -> Invites:
        """Ленивая просрочка: истёкшие pending-приглашения закрываются при чтении."""
        now = utc_now()
        expired = [item for item in invites if item.expires_at <= now]
        for item in expired:
            item.status = ProjectInviteStatus.EXPIRED
        if expired:
            await self._transaction.commit()
        return [item for item in invites if item.status is ProjectInviteStatus.PENDING]

    async def _own_pending_invite(self, user: User, invite_id: uuid.UUID) -> ProjectInvite:
        invite = await self._invites.get(invite_id)
        if invite is None or invite.invitee_id != user.id:
            raise NotFoundError("Приглашение не найдено")
        if not await self._fresh([invite]):
            raise ConflictError("Приглашение уже неактивно")
        return invite

    def _send_invite_email(
        self,
        invite: ProjectInvite,
        project: Project,
        inviter: User,
        to_email: str,
    ) -> None:
        base_url = self._settings.frontend_base_url.rstrip("/")
        rendered = self._renderer.render(
            INVITE_EMAIL_CATEGORY,
            {
                "project_title": project.title,
                "inviter_name": inviter.name or inviter.login,
                "role_label": ROLE_LABELS[invite.role],
                "invites_url": f"{base_url}/me",
                "logo_url": f"{base_url}/brandmark-email.png",
            },
        )
        self._email_jobs.add(
            EmailJobOutbox(
                to_email=to_email,
                subject=rendered.subject,
                html_body=rendered.html,
                text_body=rendered.text,
                category=INVITE_EMAIL_CATEGORY,
                queue=EmailQueue.TRANSACTIONAL,
                dispatched_at=None,
                attempts=0,
                last_error=None,
            ),
        )
