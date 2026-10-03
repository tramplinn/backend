from datetime import datetime

import uuid_utils.compat as uuid
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from tramplin.models.assets import Asset
from tramplin.models.base import Base, UUIDPrimaryKey
from tramplin.models.enums import (
    ProfileBlock,
    ProjectInviteStatus,
    ProjectLinkKind,
    ProjectRole,
    ProjectStatus,
    ProjectVisibility,
)
from tramplin.models.users import User


class Project(UUIDPrimaryKey):
    """Проект пользователей: карточка с README, ссылками и командой.

    По умолчанию private: черновик не должен случайно оказаться в каталоге.
    """

    __tablename__ = "projects"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_projects_slug"),
        CheckConstraint("char_length(readme_md) <= 100000", name="readme_md_length"),
    )

    slug: Mapped[str] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(String(120))
    summary: Mapped[str | None] = mapped_column(String(280))
    readme_md: Mapped[str] = mapped_column(Text(), default="", server_default="")
    status: Mapped[ProjectStatus] = mapped_column(
        default=ProjectStatus.IDEA,
        server_default=ProjectStatus.IDEA.value,
    )
    visibility: Mapped[ProjectVisibility] = mapped_column(
        default=ProjectVisibility.PRIVATE,
        server_default=ProjectVisibility.PRIVATE.value,
    )
    logo_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL")
    )
    status_changed_at: Mapped[datetime]

    logo_asset: Mapped[Asset | None] = relationship(foreign_keys=[logo_asset_id])
    members: Mapped[list[ProjectMember]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="ProjectMember.joined_at",
    )
    links: Mapped[list[ProjectLink]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="ProjectLink.position",
    )


class ProjectMember(Base):
    """Участие в проекте. Порядок в блоке «Проекты» профиля — свойство участия,
    а не проекта: у каждого участника своя витрина."""

    __tablename__ = "project_members"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    role: Mapped[ProjectRole]
    title: Mapped[str | None] = mapped_column(String(80))
    show_in_profile: Mapped[bool] = mapped_column(Boolean(), default=True, server_default="true")
    profile_position: Mapped[int] = mapped_column(SmallInteger(), default=0, server_default="0")
    joined_at: Mapped[datetime]

    project: Mapped[Project] = relationship(back_populates="members")
    user: Mapped[User] = relationship(foreign_keys=[user_id])


class ProjectInvite(UUIDPrimaryKey):
    """Просроченные приглашения переводятся в expired лениво, при чтении."""

    __tablename__ = "project_invites"
    __table_args__ = (CheckConstraint("role <> 'owner'", name="role_not_owner"),)

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    invitee_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    inviter_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    role: Mapped[ProjectRole]
    title: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[ProjectInviteStatus] = mapped_column(
        default=ProjectInviteStatus.PENDING,
        server_default=ProjectInviteStatus.PENDING.value,
    )
    expires_at: Mapped[datetime]
    responded_at: Mapped[datetime | None]

    project: Mapped[Project] = relationship(foreign_keys=[project_id])
    invitee: Mapped[User] = relationship(foreign_keys=[invitee_id])
    inviter: Mapped[User | None] = relationship(foreign_keys=[inviter_id])


class ProjectLink(UUIDPrimaryKey):
    __tablename__ = "project_links"

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    kind: Mapped[ProjectLinkKind]
    url: Mapped[str] = mapped_column(String(2048))
    label: Mapped[str | None] = mapped_column(String(120))
    position: Mapped[int] = mapped_column(SmallInteger(), default=0)

    project: Mapped[Project] = relationship(back_populates="links")


class ProjectStatusEvent(UUIDPrimaryKey):
    """История статусов; from_status пуст у события создания проекта."""

    __tablename__ = "project_status_events"

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    from_status: Mapped[ProjectStatus | None]
    to_status: Mapped[ProjectStatus]
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    actor: Mapped[User | None] = relationship(foreign_keys=[actor_id])


class UserProfileBlock(Base):
    """Раскладка публичного профиля. Строк нет, пока пользователь её не сохранил."""

    __tablename__ = "user_profile_blocks"
    __table_args__ = (
        CheckConstraint("position >= 0", name="position_non_negative"),
        UniqueConstraint(
            "user_id",
            "position",
            name="uq_user_profile_blocks_user_id_position",
            deferrable=True,
            initially="DEFERRED",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    block: Mapped[ProfileBlock] = mapped_column(primary_key=True)
    position: Mapped[int] = mapped_column(SmallInteger())
    is_visible: Mapped[bool] = mapped_column(Boolean(), default=True, server_default="true")


Index(
    "uq_project_members_project_id_owner",
    ProjectMember.project_id,
    unique=True,
    postgresql_where=text("role = 'owner'"),
)
Index("ix_project_members_user_id", ProjectMember.user_id)
Index(
    "uq_project_invites_project_id_invitee_id_pending",
    ProjectInvite.project_id,
    ProjectInvite.invitee_id,
    unique=True,
    postgresql_where=text("status = 'pending'"),
)
Index("ix_project_invites_invitee_id", ProjectInvite.invitee_id)
Index("ix_projects_visibility_status", Project.visibility, Project.status)
Index("ix_projects_updated_at", Project.updated_at)
Index("ix_projects_status_changed_at", Project.status_changed_at)
Index("ix_projects_logo_asset_id", Project.logo_asset_id)
Index("ix_project_links_project_id_kind", ProjectLink.project_id, ProjectLink.kind)
Index("ix_project_status_events_project_id", ProjectStatusEvent.project_id)
