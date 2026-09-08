from typing import Any, cast
from unittest.mock import AsyncMock

from tramplin.core.errors import InvalidAlgorithmProblemError, InvalidQuizError
from tramplin.models.algorithms import PracticeSet
from tramplin.models.base import new_id
from tramplin.models.content import Course, Lesson, Module, ModuleItem, Track, TrackCourse
from tramplin.models.enums import ContentStatus
from tramplin.models.quizzes import Quiz
from tramplin.services.publish_cascade import PublishCascadeService


def item_for(content: Lesson | Quiz | PracticeSet) -> ModuleItem:
    item = ModuleItem(position=0)
    if isinstance(content, Lesson):
        item.lesson = content
    elif isinstance(content, Quiz):
        item.quiz = content
    else:
        item.practice_set = content
    return item


def make_service(
    *,
    module_tree: Module | None = None,
    course_tree: Course | None = None,
    track_tree: Track | None = None,
    lesson_update: Any = None,
    quiz_update: Any = None,
    set_update: Any = None,
) -> tuple[PublishCascadeService, dict[str, AsyncMock]]:
    mocks = {
        "module_update": AsyncMock(),
        "course_update": AsyncMock(),
        "track_update": AsyncMock(),
        "lesson_update": lesson_update or AsyncMock(),
        "quiz_update": quiz_update or AsyncMock(),
        "set_update": set_update or AsyncMock(),
    }
    modules = cast(
        Any,
        AsyncMock(get_tree=AsyncMock(return_value=module_tree), update=mocks["module_update"]),
    )
    courses = cast(
        Any,
        AsyncMock(get_tree=AsyncMock(return_value=course_tree), update=mocks["course_update"]),
    )
    tracks = cast(
        Any, AsyncMock(get_tree=AsyncMock(return_value=track_tree), update=mocks["track_update"])
    )
    lessons = cast(Any, AsyncMock(update=mocks["lesson_update"]))
    quizzes = cast(Any, AsyncMock(update=mocks["quiz_update"]))
    algorithm_authoring = cast(Any, AsyncMock(update_set=mocks["set_update"]))
    service = PublishCascadeService(modules, courses, tracks, lessons, quizzes, algorithm_authoring)
    return service, mocks


async def test_publish_module_publishes_module_and_draft_items() -> None:
    lesson = Lesson(title="L", slug="l", status=ContentStatus.DRAFT, module_id=new_id())
    published_quiz = Quiz(title="Q", slug="q", status=ContentStatus.PUBLISHED, module_id=new_id())
    module = Module(title="M", slug="m", status=ContentStatus.DRAFT)
    module.items = [item_for(lesson), item_for(published_quiz)]
    service, mocks = make_service(module_tree=module)
    actor = new_id()

    report = await service.publish_module(module.id, actor)

    mocks["module_update"].assert_awaited_once_with(
        module.id, {"status": ContentStatus.PUBLISHED}, actor
    )
    mocks["lesson_update"].assert_awaited_once_with(
        lesson.id, {"status": ContentStatus.PUBLISHED}, actor
    )
    # Уже опубликованный тест не трогаем вообще.
    mocks["quiz_update"].assert_not_awaited()
    assert set(report.published) == {module.id, lesson.id}
    assert report.skipped == []


async def test_publish_module_never_touches_already_published_module() -> None:
    module = Module(title="M", slug="m", status=ContentStatus.PUBLISHED)
    module.items = []
    service, mocks = make_service(module_tree=module)

    report = await service.publish_module(module.id, new_id())

    mocks["module_update"].assert_not_awaited()
    assert report.published == []


async def test_publish_module_skips_items_that_fail_validation_but_continues() -> None:
    bad_quiz = Quiz(title="Q", slug="q", status=ContentStatus.DRAFT, module_id=new_id())
    good_lesson = Lesson(title="L", slug="l", status=ContentStatus.DRAFT, module_id=new_id())
    bad_set = PracticeSet(title="S", status=ContentStatus.DRAFT)
    module = Module(title="M", slug="m", status=ContentStatus.DRAFT)
    module.items = [item_for(bad_quiz), item_for(good_lesson), item_for(bad_set)]

    quiz_update = AsyncMock(side_effect=InvalidQuizError("Нельзя опубликовать тест без вопросов"))
    set_update = AsyncMock(
        side_effect=InvalidAlgorithmProblemError("Набор должен содержать опубликованные задачи")
    )
    service, mocks = make_service(
        module_tree=module, quiz_update=quiz_update, set_update=set_update
    )
    actor = new_id()

    report = await service.publish_module(module.id, actor)

    # Провал одного пункта не мешает остальным — best-effort, не all-or-nothing.
    mocks["lesson_update"].assert_awaited_once_with(
        good_lesson.id, {"status": ContentStatus.PUBLISHED}, actor
    )
    assert module.id in report.published
    assert good_lesson.id in report.published
    skipped_by_id = {skip.id: skip for skip in report.skipped}
    assert skipped_by_id[bad_quiz.id].reason == "Нельзя опубликовать тест без вопросов"
    assert skipped_by_id[bad_quiz.id].kind == "quiz"
    assert skipped_by_id[bad_set.id].reason == "Набор должен содержать опубликованные задачи"
    assert skipped_by_id[bad_set.id].kind == "practice_set"


async def test_publish_course_publishes_course_and_its_modules() -> None:
    lesson = Lesson(title="L", slug="l", status=ContentStatus.DRAFT, module_id=new_id())
    module = Module(title="M", slug="m", status=ContentStatus.DRAFT)
    module.items = [item_for(lesson)]
    course = Course(title="C", slug="c", status=ContentStatus.DRAFT)
    course.modules = [module]
    service, mocks = make_service(course_tree=course)
    actor = new_id()

    report = await service.publish_course(course.id, actor)

    mocks["course_update"].assert_awaited_once_with(
        course.id, {"status": ContentStatus.PUBLISHED}, actor
    )
    assert set(report.published) == {course.id, module.id, lesson.id}


async def test_publish_track_publishes_track_and_every_course() -> None:
    lesson = Lesson(title="L", slug="l", status=ContentStatus.DRAFT, module_id=new_id())
    module = Module(title="M", slug="m", status=ContentStatus.DRAFT)
    module.items = [item_for(lesson)]
    course = Course(title="C", slug="c", status=ContentStatus.DRAFT)
    course.modules = [module]
    track = Track(title="T", slug="t", status=ContentStatus.DRAFT)
    track.courses = [TrackCourse(track_id=new_id(), course_id=course.id, position=0)]
    service, mocks = make_service(track_tree=track, course_tree=course)
    actor = new_id()

    report = await service.publish_track(track.id, actor)

    mocks["track_update"].assert_awaited_once_with(
        track.id, {"status": ContentStatus.PUBLISHED}, actor
    )
    assert set(report.published) == {track.id, course.id, module.id, lesson.id}
