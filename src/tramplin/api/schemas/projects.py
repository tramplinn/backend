from datetime import datetime
from typing import Final
from urllib.parse import urlsplit

import uuid_utils.compat as uuid
from pydantic import Field, field_validator

from tramplin.api.schemas.base import ApiModel
from tramplin.models.enums import (
    ProfileBlock,
    ProjectInviteStatus,
    ProjectLinkKind,
    ProjectRole,
    ProjectStatus,
    ProjectVisibility,
)

PROJECT_SLUG_PATTERN: Final = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
README_MAX_LENGTH: Final = 100_000
MAX_LINKS: Final = 20


class ProjectCreate(ApiModel):
    title: str = Field(min_length=1, max_length=120)
    summary: str | None = Field(default=None, max_length=280)
    visibility: ProjectVisibility = ProjectVisibility.PRIVATE


class ProjectUpdate(ApiModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    slug: str | None = Field(default=None, pattern=PROJECT_SLUG_PATTERN, max_length=80)
    summary: str | None = Field(default=None, max_length=280)
    readme_md: str | None = Field(default=None, max_length=README_MAX_LENGTH)
    visibility: ProjectVisibility | None = None
    logo_asset_id: uuid.UUID | None = None


class ProjectStatusIn(ApiModel):
    status: ProjectStatus


class ProjectLinkIn(ApiModel):
    kind: ProjectLinkKind
    url: str = Field(min_length=1, max_length=2048)
    label: str | None = Field(default=None, max_length=120)

    @field_validator("url")
    @classmethod
    def url_is_http(cls, value: str) -> str:
        """javascript: и прочие схемы отрезаем здесь: ссылка уходит в href как есть."""
        value = value.strip()
        parts = urlsplit(value)
        if parts.scheme not in {"http", "https"} or not parts.netloc:
            raise ValueError("Ссылка должна начинаться с http:// или https://")
        return value


class ProjectLinksIn(ApiModel):
    links: list[ProjectLinkIn] = Field(max_length=MAX_LINKS)


class ProjectLinkOut(ApiModel):
    id: uuid.UUID
    kind: ProjectLinkKind
    url: str
    label: str | None
    position: int


class ProjectMemberOut(ApiModel):
    user_id: uuid.UUID
    login: str
    name: str | None
    avatar_url: str | None
    role: ProjectRole
    title: str | None
    joined_at: datetime


class ProjectMemberUpdate(ApiModel):
    role: ProjectRole | None = None
    title: str | None = Field(default=None, max_length=80)


class ProjectTransferIn(ApiModel):
    login: str = Field(min_length=1, max_length=64)


class ProjectCardOut(ApiModel):
    id: uuid.UUID
    slug: str
    title: str
    summary: str | None
    status: ProjectStatus
    visibility: ProjectVisibility
    logo_url: str | None
    members_count: int
    my_role: ProjectRole | None = None
    member_title: str | None = None
    show_in_profile: bool | None = None
    updated_at: datetime


class ProjectOut(ProjectCardOut):
    readme_md: str
    logo_asset_id: uuid.UUID | None
    links: list[ProjectLinkOut]
    members: list[ProjectMemberOut]
    status_changed_at: datetime
    created_at: datetime


class ProjectStatusEventOut(ApiModel):
    id: uuid.UUID
    from_status: ProjectStatus | None
    to_status: ProjectStatus
    actor_login: str | None
    created_at: datetime


class ProjectInviteCreate(ApiModel):
    login: str = Field(min_length=1, max_length=64)
    role: ProjectRole
    title: str | None = Field(default=None, max_length=80)

    @field_validator("role")
    @classmethod
    def role_is_not_owner(cls, value: ProjectRole) -> ProjectRole:
        if value is ProjectRole.OWNER:
            raise ValueError("Владельца нельзя пригласить — только передать владение")
        return value


class ProjectInviteProjectOut(ApiModel):
    slug: str
    title: str
    logo_url: str | None


class ProjectInviteOut(ApiModel):
    id: uuid.UUID
    project: ProjectInviteProjectOut
    invitee_login: str
    inviter_login: str | None
    role: ProjectRole
    title: str | None
    status: ProjectInviteStatus
    expires_at: datetime
    created_at: datetime


class ProfileProjectOrderItem(ApiModel):
    project_id: uuid.UUID
    show_in_profile: bool = True


class ProfileProjectsOrderIn(ApiModel):
    items: list[ProfileProjectOrderItem]


class ProfileLayoutItemSchema(ApiModel):
    block: ProfileBlock
    visible: bool = True


class ProfileLayoutIn(ApiModel):
    blocks: list[ProfileLayoutItemSchema]


class ProfileLayoutOut(ApiModel):
    blocks: list[ProfileLayoutItemSchema]
