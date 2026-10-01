from typing import Literal

import uuid_utils.compat as uuid
from pydantic import Field

from tramplin.api.schemas.base import ApiModel
from tramplin.api.schemas.directories import CompanyOut, InterestOut, UniversityOut
from tramplin.api.schemas.identities import IdentityOut
from tramplin.models.enums import UserRole

Specialty = Literal["frontend", "backend", "fullstack", "mobile", "data", "devops", "qa"]
DeveloperGrade = Literal["learning", "junior", "middle", "senior"]
Locale = Literal["ru", "en"]


class UserAdminUpdate(ApiModel):
    name: str | None = Field(default=None, max_length=200)
    student_number: str | None = Field(default=None, max_length=32)
    role: UserRole | None = None
    is_active: bool | None = None


class UserProfileUpdate(ApiModel):
    name: str | None = Field(default=None, max_length=200)
    headline: str | None = Field(default=None, max_length=120)
    bio: str | None = Field(default=None, max_length=1000)
    specialty: Specialty | None = None
    grade: DeveloperGrade | None = None
    experience_years: int | None = Field(default=None, ge=0, le=80)
    company: str | None = Field(default=None, max_length=200)
    university: str | None = Field(default=None, max_length=200)
    interests: list[str] | None = Field(default=None, max_length=20)
    resume_asset_id: uuid.UUID | None = None
    preferred_locale: Locale | None = None


class UserOut(ApiModel):
    id: uuid.UUID
    login: str
    name: str | None
    email: str | None
    avatar_url: str | None
    student_number: str | None
    role: UserRole
    is_active: bool
    headline: str | None
    bio: str | None
    specialty: Specialty | None
    grade: DeveloperGrade | None
    experience_years: int | None
    company: CompanyOut | None
    university: UniversityOut | None
    interests: list[InterestOut]
    resume_asset_id: uuid.UUID | None
    resume_url: str | None = None


class PublicUserOut(ApiModel):
    id: uuid.UUID
    login: str
    name: str | None
    avatar_url: str | None
    headline: str | None
    specialty: Specialty | None
    grade: DeveloperGrade | None
    experience_years: int | None
    company: CompanyOut | None
    university: UniversityOut | None
    interests: list[InterestOut]


class CourseActivityOut(ApiModel):
    slug: str
    title: str
    color: str | None
    completed_lessons: int
    total_lessons: int


class PublicProfileOut(PublicUserOut):
    bio: str | None
    completed_lessons: int
    passed_quizzes: int
    solved_algorithms: int
    active_courses: list[CourseActivityOut] = Field(default_factory=list)
    resume_url: str | None = None


class MeOut(UserOut):
    preferred_locale: Locale | None = None
    identities: list[IdentityOut] = Field(default_factory=list)
