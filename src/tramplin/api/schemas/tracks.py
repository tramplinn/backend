import uuid_utils.compat as uuid
from pydantic import Field, field_validator

from tramplin.api.schemas.base import ApiModel
from tramplin.api.schemas.courses import CourseOut
from tramplin.models.enums import ContentStatus


class TrackCreate(ApiModel):
    title: str = Field(min_length=1, max_length=200)
    slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=120)
    description: str | None = None
    color: str | None = Field(default=None, max_length=16)
    status: ContentStatus = ContentStatus.DRAFT


class TrackUpdate(ApiModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    slug: str | None = Field(
        default=None,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
        max_length=120,
    )
    description: str | None = None
    color: str | None = Field(default=None, max_length=16)
    status: ContentStatus | None = None


class TrackCoursesOrder(ApiModel):
    course_ids: list[uuid.UUID]

    @field_validator("course_ids")
    @classmethod
    def course_ids_are_unique(cls, value: list[uuid.UUID]) -> list[uuid.UUID]:
        if len(value) != len(set(value)):
            raise ValueError("course_ids не должны повторяться")
        return value


class TrackCourseOut(ApiModel):
    position: int
    course: CourseOut


class TrackOut(ApiModel):
    id: uuid.UUID
    title: str
    slug: str
    description: str | None
    color: str | None
    status: ContentStatus
    courses: list[TrackCourseOut] = Field(default_factory=list)
