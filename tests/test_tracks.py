from typing import Any, cast

import pytest

from tests.fakes import FakeSession
from tramplin.api.schemas.tracks import TrackCoursesOrder
from tramplin.core.errors import ConflictError, NotFoundError
from tramplin.models.base import new_id
from tramplin.models.content import Course, Track, TrackCourse
from tramplin.services.tracks import TrackService


class TrackRepositoryFake:
    def __init__(self, track: Track, links: list[TrackCourse]) -> None:
        self.track = track
        self.links = links
        self.added_links: list[TrackCourse] = []
        self.locked_ids: list[object] = []

    async def get(self, track_id: object) -> Track | None:
        return self.track if track_id == self.track.id else None

    async def get_for_update(self, track_id: object) -> Track | None:
        self.locked_ids.append(track_id)
        return self.track if track_id == self.track.id else None

    async def get_course_link(
        self,
        track_id: object,
        course_id: object,
    ) -> TrackCourse | None:
        return next(
            (
                link
                for link in self.links
                if (track_id, course_id) == (link.track_id, link.course_id)
            ),
            None,
        )

    async def list_course_links(self, track_id: object) -> list[TrackCourse]:
        return [link for link in self.links if link.track_id == track_id]

    def add_course_link(self, link: TrackCourse) -> TrackCourse:
        self.added_links.append(link)
        return link


class CourseRepositoryFake:
    def __init__(self, course: Course) -> None:
        self.course = course

    async def get(self, course_id: object) -> Course | None:
        return self.course if course_id == self.course.id else None


async def test_attach_course_is_idempotent() -> None:
    track = Track(title="Backend", slug="backend")
    course = Course(title="Python", slug="python")
    link = TrackCourse(track_id=track.id, course_id=course.id, position=1)
    tracks = TrackRepositoryFake(track, [link])
    session = FakeSession()
    actor_id = new_id()
    service = TrackService(
        session,
        cast(Any, tracks),
        cast(Any, CourseRepositoryFake(course)),
    )

    await service.attach_course(track.id, course.id, actor_id=actor_id)

    assert tracks.locked_ids == [track.id]
    assert link.position == 1
    assert tracks.added_links == []
    assert session.commits == 0


async def test_reorder_courses_updates_every_position_atomically() -> None:
    track = Track(title="Backend", slug="backend")
    first = Course(title="Python", slug="python")
    second = Course(title="Databases", slug="databases")
    links = [
        TrackCourse(track_id=track.id, course_id=first.id, position=0),
        TrackCourse(track_id=track.id, course_id=second.id, position=1),
    ]
    tracks = TrackRepositoryFake(track, links)
    session = FakeSession()
    actor_id = new_id()
    service = TrackService(
        session,
        cast(Any, tracks),
        cast(Any, CourseRepositoryFake(first)),
    )

    await service.reorder_courses(track.id, [second.id, first.id], actor_id)

    assert tracks.locked_ids == [track.id]
    assert [(link.course_id, link.position) for link in links] == [
        (first.id, 1),
        (second.id, 0),
    ]
    assert all(link.updated_by == actor_id for link in links)
    assert session.commits == 1


async def test_reorder_courses_validates_track_and_exact_course_set() -> None:
    track = Track(title="Backend", slug="backend")
    course = Course(title="Python", slug="python")
    link = TrackCourse(track_id=track.id, course_id=course.id, position=0)
    tracks = TrackRepositoryFake(track, [link])
    service = TrackService(
        FakeSession(),
        cast(Any, tracks),
        cast(Any, CourseRepositoryFake(course)),
    )

    with pytest.raises(ConflictError):
        await service.reorder_courses(track.id, [], new_id())
    tracks.track = Track(title="Other", slug="other")
    with pytest.raises(NotFoundError):
        await service.reorder_courses(track.id, [course.id], new_id())
    with pytest.raises(ValueError):
        TrackCoursesOrder(course_ids=[course.id, course.id])


async def test_get_tree_returns_track_or_raises_not_found() -> None:
    track = Track(title="Backend", slug="backend")
    service = TrackService(
        FakeSession(),
        cast(Any, TrackRepositoryFake(track, [])),
        cast(Any, CourseRepositoryFake(Course(title="Python", slug="python"))),
    )

    assert await service.get_tree(track.id) is track
    with pytest.raises(NotFoundError):
        await service.get_tree(new_id())
