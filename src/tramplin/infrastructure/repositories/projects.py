from collections.abc import Sequence
from typing import Any

import uuid_utils.compat as uuid
from sqlalchemy import ColumnElement, delete, exists, func, or_, select
from sqlalchemy.orm import selectinload

from tramplin.infrastructure.repositories.base import Repository
from tramplin.models.enums import ProjectInviteStatus, ProjectVisibility
from tramplin.models.projects import (
    Project,
    ProjectInvite,
    ProjectLink,
    ProjectMember,
    ProjectStatusEvent,
    UserProfileBlock,
)
from tramplin.models.users import User
from tramplin.services.projects import ProjectCatalogFilters, ProjectSort

# Участники, их пользователи, ссылки и логотип нужны любой выдаче проекта;
# в async-сессии ленивая подгрузка падает MissingGreenlet, поэтому грузим сразу.
_PROJECT_LOAD_OPTIONS = (
    selectinload(Project.members).selectinload(ProjectMember.user),
    selectinload(Project.links),
    selectinload(Project.logo_asset),
)
_SORT_ORDER: dict[ProjectSort, tuple[Any, ...]] = {
    "updated": (Project.updated_at.desc(), Project.id.desc()),
    "created": (Project.created_at.desc(), Project.id.desc()),
    "status_changed": (Project.status_changed_at.desc(), Project.id.desc()),
    "title": (func.lower(Project.title), Project.id),
}


class ProjectRepository(Repository):
    async def catalog(
        self,
        filters: ProjectCatalogFilters,
        *,
        visibilities: Sequence[ProjectVisibility],
        limit: int,
        offset: int,
    ) -> tuple[list[Project], int]:
        conditions: list[ColumnElement[bool]] = [Project.visibility.in_(list(visibilities))]
        if filters.query:
            pattern = f"%{filters.query}%"
            conditions.append(or_(Project.title.ilike(pattern), Project.summary.ilike(pattern)))
        if filters.statuses:
            conditions.append(Project.status.in_(list(filters.statuses)))
        for kind in filters.link_kinds:
            # Каждый выбранный тип ссылки обязателен: «с репозиторием» И «с демо».
            conditions.append(
                exists().where(ProjectLink.project_id == Project.id, ProjectLink.kind == kind)
            )
        if filters.member_login:
            conditions.append(
                exists().where(
                    ProjectMember.project_id == Project.id,
                    ProjectMember.show_in_profile.is_(True),
                    ProjectMember.user_id == User.id,
                    User.login == filters.member_login,
                    User.is_active.is_(True),
                )
            )
        total = await self._session.scalar(
            select(func.count()).select_from(Project).where(*conditions)
        )
        stmt = (
            select(Project)
            .where(*conditions)
            .order_by(*_SORT_ORDER[filters.sort])
            .limit(limit)
            .offset(offset)
            .options(*_PROJECT_LOAD_OPTIONS)
        )
        return list(await self._session.scalars(stmt)), total or 0

    async def list_for_member(self, user_id: uuid.UUID) -> list[Project]:
        stmt = (
            select(Project)
            .join(ProjectMember, ProjectMember.project_id == Project.id)
            .where(ProjectMember.user_id == user_id)
            .order_by(ProjectMember.profile_position, Project.updated_at.desc())
            .options(*_PROJECT_LOAD_OPTIONS)
        )
        return list(await self._session.scalars(stmt))

    async def get_by_slug(self, slug: str) -> Project | None:
        stmt = select(Project).where(Project.slug == slug).options(*_PROJECT_LOAD_OPTIONS)
        return (await self._session.scalars(stmt)).one_or_none()

    async def slug_exists(self, slug: str) -> bool:
        stmt = select(Project.id).where(Project.slug == slug).limit(1)
        return (await self._session.scalars(stmt)).first() is not None

    async def status_events(self, project_id: uuid.UUID) -> list[ProjectStatusEvent]:
        stmt = (
            select(ProjectStatusEvent)
            .where(ProjectStatusEvent.project_id == project_id)
            .order_by(ProjectStatusEvent.created_at.desc(), ProjectStatusEvent.id.desc())
            .options(selectinload(ProjectStatusEvent.actor))
        )
        return list(await self._session.scalars(stmt))

    async def next_profile_position(self, user_id: uuid.UUID) -> int:
        current = await self._session.scalar(
            select(func.max(ProjectMember.profile_position)).where(ProjectMember.user_id == user_id)
        )
        return 0 if current is None else current + 1


class ProjectInviteRepository(Repository):
    _options = (
        selectinload(ProjectInvite.project).options(*_PROJECT_LOAD_OPTIONS),
        selectinload(ProjectInvite.invitee),
        selectinload(ProjectInvite.inviter),
    )

    async def get(self, invite_id: uuid.UUID) -> ProjectInvite | None:
        stmt = select(ProjectInvite).where(ProjectInvite.id == invite_id).options(*self._options)
        return (await self._session.scalars(stmt)).one_or_none()

    async def list_pending_for_project(self, project_id: uuid.UUID) -> list[ProjectInvite]:
        return await self._pending(ProjectInvite.project_id == project_id)

    async def list_pending_for_user(self, user_id: uuid.UUID) -> list[ProjectInvite]:
        return await self._pending(ProjectInvite.invitee_id == user_id)

    async def find_pending(
        self,
        project_id: uuid.UUID,
        invitee_id: uuid.UUID,
    ) -> ProjectInvite | None:
        found = await self._pending(
            ProjectInvite.project_id == project_id,
            ProjectInvite.invitee_id == invitee_id,
        )
        return found[0] if found else None

    async def _pending(self, *conditions: ColumnElement[bool]) -> list[ProjectInvite]:
        stmt = (
            select(ProjectInvite)
            .where(ProjectInvite.status == ProjectInviteStatus.PENDING, *conditions)
            .order_by(ProjectInvite.created_at.desc())
            .options(*self._options)
        )
        return list(await self._session.scalars(stmt))


class ProfileLayoutRepository(Repository):
    async def list_for_user(self, user_id: uuid.UUID) -> list[UserProfileBlock]:
        stmt = (
            select(UserProfileBlock)
            .where(UserProfileBlock.user_id == user_id)
            .order_by(UserProfileBlock.position)
        )
        return list(await self._session.scalars(stmt))

    async def delete_for_user(self, user_id: uuid.UUID) -> None:
        await self._session.execute(
            delete(UserProfileBlock).where(UserProfileBlock.user_id == user_id)
        )
