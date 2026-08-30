import uuid_utils.compat as uuid
from pydantic import Field

from tramplin.api.schemas.base import ApiModel
from tramplin.api.schemas.identities import IdentityOut
from tramplin.models.enums import UserRole


class UserAdminUpdate(ApiModel):
    name: str | None = Field(default=None, max_length=200)
    student_number: str | None = Field(default=None, max_length=32)
    group_id: uuid.UUID | None = None
    role: UserRole | None = None
    is_active: bool | None = None


class StudentGroupCreate(ApiModel):
    name: str = Field(min_length=1, max_length=64)
    year: int = Field(ge=2000, le=9999)


class StudentGroupUpdate(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    year: int | None = Field(default=None, ge=2000, le=9999)


class StudentGroupOut(ApiModel):
    id: uuid.UUID
    name: str
    year: int


class UserOut(ApiModel):
    id: uuid.UUID
    login: str
    name: str | None
    email: str | None
    avatar_url: str | None
    student_number: str | None
    group_id: uuid.UUID | None
    role: UserRole
    is_active: bool


class MeOut(UserOut):
    identities: list[IdentityOut] = Field(default_factory=list)
