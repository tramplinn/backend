from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock, patch

import pytest
from sqlalchemy import inspect

from tests.fakes import FakeSession
from tramplin.api.content_mapping import module_tree_out
from tramplin.core.errors import (
    ConflictError,
    InvalidLessonContentError,
    InvalidQuizError,
    InvalidUpdateError,
    NotFoundError,
)
from tramplin.models.assets import Asset
from tramplin.models.base import new_id
from tramplin.models.content import (
    Course,
    InterviewCard,
    Lesson,
    Module,
    ModuleDep,
    ModuleItem,
    Track,
)
from tramplin.models.enums import AssetMime, ContentStatus, QuestionType
from tramplin.models.quizzes import Quiz, QuizQuestion
from tramplin.services.courses import CourseService
from tramplin.services.entity_updates import (
    apply_order,
    mark_created,
    mark_updated,
    validate_required_updates,
)
from tramplin.services.lessons import LessonService
from tramplin.services.modules import ModuleService
from tramplin.services.quizzes import QuizService
from tramplin.services.tracks import TrackService


def dependency(**values: Any) -> Any:
    return cast(Any, SimpleNamespace(**values))


def content_model_kwargs() -> dict[str, Any]:
    return {"title": "Title", "slug": "title", "status": ContentStatus.DRAFT}


async def test_course_service_crud_and_not_found() -> None:
    course = Course(**content_model_kwargs())
    session = FakeSession()
    repository = dependency(
        list=AsyncMock(return_value=[course]),
        get=AsyncMock(return_value=course),
        get_by_slug=AsyncMock(return_value=course),
        add=Mock(),
        delete_cascade=AsyncMock(),
    )
    assets = dependency(get=AsyncMock(return_value=None))
    service = CourseService(session, repository, assets)
    actor = new_id()

    assert await service.list(published_only=False) == [course]
    assert await service.get("title", published_only=False) is course
    assert await service.create(course, actor) is course
    assert await service.update(course.id, {"title": "Updated"}, actor) is course
    await service.delete(course.id)
    assert course.title == "Updated"
    assert session.commits == 3

    repository.get_by_slug.return_value = None
    with pytest.raises(NotFoundError):
        await service.get("missing")
    repository.get.return_value = None
    with pytest.raises(NotFoundError):
        await service.update(new_id(), {}, actor)
    with pytest.raises(NotFoundError):
        await service.delete(new_id())


async def test_course_cover_must_reference_an_image_asset() -> None:
    course = Course(**content_model_kwargs())
    image = Asset(filename="cover.webp", s3_key="cover", mime=AssetMime.WEBP, size=10)
    pdf = Asset(filename="book.pdf", s3_key="book", mime=AssetMime.PDF, size=10)
    session = FakeSession()
    repository = dependency(get=AsyncMock(return_value=course))
    assets = dependency(get=AsyncMock(return_value=image))
    service = CourseService(session, repository, assets)
    actor = new_id()

    result = await service.update(course.id, {"cover_asset_id": image.id}, actor)

    assert result.cover_asset is image
    assert result.cover_asset_id == image.id

    assets.get.return_value = None
    with pytest.raises(NotFoundError, match="обложки"):
        await service.update(course.id, {"cover_asset_id": new_id()}, actor)

    assets.get.return_value = pdf
    with pytest.raises(InvalidUpdateError, match="изображение"):
        await service.update(course.id, {"cover_asset_id": pdf.id}, actor)


async def test_module_service_crud_dependencies_and_validation() -> None:
    course = Course(**content_model_kwargs())
    module = Module(course_id=course.id, position=0, **content_model_kwargs())
    other = Module(course_id=course.id, position=1, title="Other", slug="other")
    edge = ModuleDep(module_id=module.id, depends_on_id=other.id)
    session = FakeSession()
    modules = dependency(
        get=AsyncMock(return_value=module),
        get_for_update=AsyncMock(return_value=module),
        add=Mock(),
        delete_cascade=AsyncMock(),
        list_dependencies=AsyncMock(return_value=[edge]),
        get_dependency=AsyncMock(return_value=None),
        add_dependency=Mock(),
        delete_dependency=AsyncMock(),
    )
    courses = dependency(
        get=AsyncMock(return_value=course),
        get_by_slug=AsyncMock(return_value=course),
    )
    service = ModuleService(session, modules, courses)
    actor = new_id()

    assert await service.list_dependencies("title", published_only=False) == [edge]
    assert await service.create(course.id, module, actor) is module
    assert await service.update(module.id, {"title": "Updated"}, actor) is module
    modules.get.return_value = other
    await service.add_dependency(module.id, other.id, actor)
    modules.get_dependency.return_value = edge
    await service.remove_dependency(module.id, other.id)
    modules.get.side_effect = None
    modules.get.return_value = module
    await service.delete(module.id)

    courses.get_by_slug.return_value = None
    with pytest.raises(NotFoundError):
        await service.list_dependencies("missing")
    courses.get.return_value = None
    with pytest.raises(NotFoundError):
        await service.create(course.id, module, actor)
    modules.get.return_value = None
    with pytest.raises(NotFoundError):
        await service.update(module.id, {}, actor)
    with pytest.raises(NotFoundError):
        await service.delete(module.id)
    modules.get_for_update.return_value = None
    with pytest.raises(NotFoundError):
        await service.add_dependency(module.id, other.id, actor)
    modules.get_for_update.return_value = module
    modules.get.return_value = module
    with pytest.raises(ConflictError, match="самого себя"):
        await service.add_dependency(module.id, module.id, actor)
    foreign = Module(course_id=new_id(), position=2, title="Foreign", slug="foreign")
    modules.get.return_value = foreign
    with pytest.raises(ConflictError, match="одному курсу"):
        await service.add_dependency(module.id, foreign.id, actor)
    modules.get.return_value = other
    modules.get_dependency.return_value = edge
    with pytest.raises(ConflictError, match="существует"):
        await service.add_dependency(module.id, other.id, actor)
    modules.get_dependency.return_value = None
    modules.list_dependencies.return_value = [
        ModuleDep(module_id=other.id, depends_on_id=module.id)
    ]
    with pytest.raises(ConflictError, match="цикл"):
        await service.add_dependency(module.id, other.id, actor)
    modules.get_dependency.return_value = None
    with pytest.raises(NotFoundError):
        await service.remove_dependency(module.id, other.id)


async def test_lesson_service_crud_cards_and_rendering_errors() -> None:
    module = Module(course_id=new_id(), position=0, **content_model_kwargs())
    lesson = Lesson(
        module_id=module.id,
        body_md=":::interview\nQ\n---\nA\n:::",
        **content_model_kwargs(),
    )
    card = InterviewCard(lesson_id=lesson.id, position=0, question_md="Q", answer_md="A")
    session = FakeSession()
    lessons = dependency(
        get=AsyncMock(return_value=lesson),
        get_with_interview_cards=AsyncMock(return_value=lesson),
        list_interview_cards=AsyncMock(return_value=[card]),
        add=Mock(),
        delete=AsyncMock(),
    )
    modules = dependency(
        get_for_update=AsyncMock(return_value=module),
        list_items=AsyncMock(return_value=[]),
        add_item=Mock(),
    )
    service = LessonService(session, lessons, modules)
    actor = new_id()

    with patch(
        "tramplin.services.lessons.to_thread.run_sync",
        new=AsyncMock(side_effect=lambda function, body: function(body)),
    ):
        assert await service.get(lesson.id, published_only=False) is lesson
        assert await service.list_interview_cards(lesson.id) == [card]
        assert await service.create(module.id, lesson, actor) is lesson
        assert lesson.interview_cards[0].question_md == "Q"
        assert await service.update(lesson.id, {"body_md": "# New"}, actor) is lesson
        await service.delete(lesson.id)
        assert session.commits == 3

        lessons.get.return_value = None
        with pytest.raises(NotFoundError):
            await service.get(new_id())
        modules.get_for_update.return_value = None
        with pytest.raises(NotFoundError):
            await service.create(module.id, lesson, actor)
        lessons.get_with_interview_cards.return_value = None
        with pytest.raises(NotFoundError):
            await service.update(lesson.id, {}, actor)

        for markdown in (
            ":::interview\nQ\nA\n:::",
            ":::interview\n---\nA\n:::",
            ":::interview\nQ",
        ):
            with pytest.raises(InvalidLessonContentError):
                await service.preview(markdown)


async def test_quiz_service_all_mutations_and_validation() -> None:
    module = Module(course_id=new_id(), position=0, **content_model_kwargs())
    lesson = Lesson(module_id=module.id, body_md="", body_html="", **content_model_kwargs())
    quiz = Quiz(
        module_id=module.id,
        lesson_id=lesson.id,
        title="Quiz",
        slug="quiz",
        status=ContentStatus.DRAFT,
    )
    question = QuizQuestion(
        quiz_id=quiz.id,
        position=0,
        prompt_md="Q",
        type=QuestionType.SINGLE,
        options_json=[],
        answer_json={"value": "A"},
    )
    quiz.questions = [question]
    session = FakeSession()
    quizzes = dependency(
        get=AsyncMock(return_value=quiz),
        add=Mock(),
        delete=AsyncMock(),
        get_question=AsyncMock(return_value=question),
        add_question=Mock(),
        delete_question=AsyncMock(),
    )
    modules = dependency(
        get_for_update=AsyncMock(return_value=module),
        list_items=AsyncMock(return_value=[]),
        add_item=Mock(),
    )
    lessons = dependency(get=AsyncMock(return_value=lesson))
    attachment = Asset(filename="task.pdf", s3_key="task.pdf", mime=AssetMime.PDF, size=10)
    assets = dependency(get=AsyncMock(return_value=attachment))
    service = QuizService(session, quizzes, modules, lessons, assets)
    actor = new_id()

    assert await service.get(quiz.id) is quiz
    assert await service.create(module.id, quiz, actor) is quiz
    assert await service.update(quiz.id, {"title": "Updated"}, actor) is quiz
    assert await service.create_question(quiz.id, question, actor, [attachment.id]) is question
    assert question.attachments == [attachment]
    assert await service.update_question(question.id, {"prompt_md": "New"}, actor) is question
    await service.delete_question(question.id)
    await service.delete(quiz.id)

    quizzes.get.return_value = None
    with pytest.raises(NotFoundError):
        await service.get(new_id())
    modules.get_for_update.return_value = None
    with pytest.raises(NotFoundError):
        await service.create(module.id, quiz, actor)
    modules.get_for_update.return_value = module
    quiz.status = ContentStatus.PUBLISHED
    with pytest.raises(InvalidQuizError, match="Сначала"):
        await service.create(module.id, quiz, actor)
    quiz.status = ContentStatus.DRAFT
    quizzes.get.return_value = quiz
    quiz.questions = []
    with pytest.raises(InvalidQuizError, match="без вопросов"):
        await service.update(quiz.id, {"status": ContentStatus.PUBLISHED}, actor)
    foreign_lesson = Lesson(module_id=new_id(), **content_model_kwargs())
    lessons.get.return_value = foreign_lesson
    with pytest.raises(InvalidQuizError, match="принадлежать"):
        await service.update(quiz.id, {"lesson_id": foreign_lesson.id}, actor)
    lessons.get.return_value = None
    with pytest.raises(InvalidQuizError, match="принадлежать"):
        await service.update(quiz.id, {"lesson_id": lesson.id}, actor)
    quizzes.get_question.return_value = None
    with pytest.raises(NotFoundError):
        await service.update_question(new_id(), {}, actor)
    with pytest.raises(NotFoundError):
        await service.delete_question(new_id())


async def test_track_service_crud_attach_and_detach() -> None:
    track = Track(**content_model_kwargs())
    course = Course(**content_model_kwargs())
    session = FakeSession()
    tracks = dependency(
        list=AsyncMock(return_value=[track]),
        get=AsyncMock(return_value=track),
        get_for_update=AsyncMock(return_value=track),
        get_by_slug=AsyncMock(return_value=track),
        add=Mock(),
        delete=AsyncMock(),
        get_course_link=AsyncMock(return_value=None),
        list_course_links=AsyncMock(return_value=[]),
        add_course_link=Mock(),
        delete_course_link=AsyncMock(),
    )
    courses = dependency(get=AsyncMock(return_value=course))
    service = TrackService(session, tracks, courses)
    actor = new_id()

    assert await service.list(published_only=False) == [track]
    assert await service.get("title", published_only=False) is track
    assert await service.create(track, actor) is track
    assert await service.update(track.id, {"title": "Updated"}, actor) is track
    await service.attach_course(track.id, course.id, actor)
    link = tracks.add_course_link.call_args.args[0]
    tracks.get_course_link.return_value = link
    await service.detach_course(track.id, course.id)
    await service.delete(track.id)

    tracks.get_by_slug.return_value = None
    with pytest.raises(NotFoundError):
        await service.get("missing")
    tracks.get.return_value = None
    with pytest.raises(NotFoundError):
        await service.update(track.id, {}, actor)
    tracks.get_for_update.return_value = None
    with pytest.raises(NotFoundError):
        await service.attach_course(track.id, course.id, actor)
    with pytest.raises(NotFoundError):
        await service.delete(track.id)
    tracks.get.return_value = track
    tracks.get_for_update.return_value = track
    courses.get.return_value = None
    with pytest.raises(NotFoundError):
        await service.attach_course(track.id, course.id, actor)
    tracks.get_course_link.return_value = None
    with pytest.raises(NotFoundError):
        await service.detach_course(track.id, course.id)


def test_entity_update_helpers() -> None:
    course = Course(**content_model_kwargs())
    actor = new_id()
    validate_required_updates({"title": "Updated"}, {"title"})
    mark_created(course, actor)
    mark_updated(course, actor)
    assert course.created_by == actor
    with pytest.raises(InvalidUpdateError):
        validate_required_updates({"title": None}, {"title"})


def test_module_tree_mapping_preserves_one_mixed_order() -> None:
    module = Module(course_id=new_id(), position=0, **content_model_kwargs())
    lesson = Lesson(module_id=module.id, body_md="", body_html="", **content_model_kwargs())
    quiz = Quiz(module_id=module.id, title="Quiz", slug="quiz", status=ContentStatus.DRAFT)
    quiz.questions = []
    quiz_item = ModuleItem(module_id=module.id, position=0, quiz_id=quiz.id, quiz=quiz)
    lesson_item = ModuleItem(
        module_id=module.id,
        position=1,
        lesson_id=lesson.id,
        lesson=lesson,
    )
    module.items = [quiz_item, lesson_item]

    result = module_tree_out(
        module,
        published_only=False,
        asset_base_url="https://assets.test",
    )

    assert [item.kind for item in result.items] == ["quiz", "lesson"]
    assert [item.id for item in result.items] == [quiz_item.id, lesson_item.id]


async def test_track_service_create_loads_courses_collection() -> None:
    """Ответ роута читает track.courses сразу после commit. Если коллекция не
    помечена загруженной, SQLAlchemy уходит в ленивую подгрузку вне
    greenlet-контекста и создание падает уже после записи в базу."""
    track = Track(**content_model_kwargs())
    tracks = dependency(add=Mock())
    service = TrackService(FakeSession(), tracks, dependency())

    await service.create(track, new_id())

    assert "courses" not in inspect(track).unloaded


async def test_quiz_service_create_loads_questions_collection() -> None:
    """То же для теста: quiz_out читает quiz.questions сразу после commit."""
    module = Module(**content_model_kwargs())
    quiz = Quiz(title="Quiz", slug="quiz", status=ContentStatus.DRAFT)
    quizzes = dependency(add=Mock())
    modules = dependency(
        get_for_update=AsyncMock(return_value=module),
        list_items=AsyncMock(return_value=[]),
        add_item=Mock(),
    )
    service = QuizService(FakeSession(), quizzes, modules, dependency(), dependency())

    await service.create(module.id, quiz, new_id())

    assert "questions" not in inspect(quiz).unloaded


async def test_module_service_reorder_content_assigns_shared_positions() -> None:
    """Уроки и тесты переставляются одним полным списком в одной транзакции."""
    module = Module(**content_model_kwargs())
    first = ModuleItem(module_id=module.id, lesson_id=new_id(), position=0)
    second = ModuleItem(module_id=module.id, quiz_id=new_id(), position=1)
    session = FakeSession()
    modules = dependency(
        get_for_update=AsyncMock(return_value=module),
        list_items=AsyncMock(return_value=[first, second]),
    )
    service = ModuleService(session, modules, dependency())
    actor = new_id()

    await service.reorder_content(module.id, [second.id, first.id], actor)

    assert (second.position, first.position) == (0, 1)
    assert first.updated_by == actor


async def test_module_service_reorder_content_rejects_partial_order() -> None:
    module = Module(**content_model_kwargs())
    first = ModuleItem(module_id=module.id, lesson_id=new_id(), position=0)
    second = ModuleItem(module_id=module.id, quiz_id=new_id(), position=1)
    service = ModuleService(
        FakeSession(),
        dependency(
            get_for_update=AsyncMock(return_value=module),
            list_items=AsyncMock(return_value=[first, second]),
        ),
        dependency(),
    )

    with pytest.raises(ConflictError):
        await service.reorder_content(module.id, [first.id], new_id())


def test_apply_order_rejects_duplicate_ids_even_when_the_set_matches() -> None:
    module = Module(**content_model_kwargs())
    item = ModuleItem(module_id=module.id, lesson_id=new_id(), position=0)

    with pytest.raises(ConflictError):
        apply_order([item], [item.id, item.id], new_id(), subject="материалы")


async def test_module_service_reorder_requires_existing_course() -> None:
    service = ModuleService(
        FakeSession(),
        dependency(list_for_course=AsyncMock(return_value=[])),
        dependency(get=AsyncMock(return_value=None)),
    )

    with pytest.raises(NotFoundError):
        await service.reorder(new_id(), [], new_id())
