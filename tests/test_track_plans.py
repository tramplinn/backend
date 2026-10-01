from typing import Any, cast

import pytest
import uuid_utils.compat as uuid

from tests.fakes import FakeSession
from tramplin.api.schemas.track_plans import TrackPlanApply
from tramplin.core.errors import InvalidPlanError
from tramplin.models.content import Course, Track, TrackCourse
from tramplin.models.enums import ContentStatus
from tramplin.services.track_plans import TrackPlanService


class TrackRepo:
    def __init__(self) -> None:
        self.track: Track | None = None
        self.links: list[TrackCourse] = []

    async def get_by_slug(self, slug: str, *, published_only: bool) -> Track | None:
        return self.track if self.track is not None and self.track.slug == slug else None

    def add(self, track: Track) -> Track:
        self.track = track
        return track

    async def list_course_links(self, track_id: uuid.UUID) -> list[TrackCourse]:
        return [link for link in self.links if link.track_id == track_id]

    def add_course_link(self, link: TrackCourse) -> TrackCourse:
        self.links.append(link)
        return link


class CourseRepo:
    def __init__(self, slugs: list[str]) -> None:
        self.courses = {slug: Course(title=slug, slug=slug) for slug in slugs}

    async def get_by_slug(self, slug: str, *, published_only: bool) -> Course | None:
        return self.courses.get(slug)


def make_service(
    slugs: list[str],
) -> tuple[TrackPlanService, FakeSession, TrackRepo, CourseRepo]:
    transaction = FakeSession()
    tracks = TrackRepo()
    courses = CourseRepo(slugs)
    return (
        TrackPlanService(transaction, cast(Any, tracks), cast(Any, courses)),
        transaction,
        tracks,
        courses,
    )


def plan(*course_slugs: str, title: str = "Backend") -> TrackPlanApply:
    return TrackPlanApply(title=title, slug="backend", course_slugs=list(course_slugs))


def order(tracks: TrackRepo, courses: CourseRepo) -> list[str]:
    slug_by_id = {course.id: slug for slug, course in courses.courses.items()}
    return [slug_by_id[link.course_id] for link in sorted(tracks.links, key=lambda x: x.position)]


async def test_apply_creates_track_and_attaches_courses_in_order() -> None:
    service, transaction, tracks, courses = make_service(["python", "sql"])

    track, report = await service.apply(plan("sql", "python"), uuid.uuid7())

    assert track.status == ContentStatus.DRAFT
    assert [(change.action, change.kind) for change in report.changes] == [
        ("create", "track"),
        ("create", "track_course"),
        ("create", "track_course"),
    ]
    assert order(tracks, courses) == ["sql", "python"]
    assert transaction.commits == 1


async def test_reapply_is_idempotent_and_additive() -> None:
    service, _, tracks, courses = make_service(["python", "sql", "go"])
    actor_id = uuid.uuid7()
    track, _ = await service.apply(plan("python", "sql"), actor_id)
    track.status = ContentStatus.PUBLISHED

    _, same = await service.apply(plan("python", "sql"), actor_id)
    assert (same.created, same.updated) == (0, 0)

    _, report = await service.apply(plan("go", "sql", title="Backend 2"), actor_id)

    assert order(tracks, courses) == ["go", "sql", "python"]
    assert report.changes[0].fields == ["title", "course_order"]
    assert track.status == ContentStatus.PUBLISHED


async def test_unknown_course_is_an_error_and_preview_does_not_commit() -> None:
    service, transaction, tracks, _ = make_service(["python"])

    report = await service.preview(plan("python", "rust"), uuid.uuid7())

    assert [(issue.code, issue.path) for issue in report.issues] == [
        ("unknown_course", "backend/rust")
    ]
    assert report.changes == []
    with pytest.raises(InvalidPlanError):
        await service.apply(plan("python", "rust"), uuid.uuid7())
    assert tracks.track is None
    assert transaction.commits == 0
