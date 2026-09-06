from typing import Any, cast

import pytest
import uuid_utils.compat as uuid

from tests.fakes import FakeSession
from tramplin.api.schemas.course_plans import CoursePlanApply
from tramplin.core.errors import InvalidQuizError, NotFoundError
from tramplin.models.assets import Asset
from tramplin.models.content import Course, Lesson, Module, ModuleItem
from tramplin.models.enums import AssetMime
from tramplin.models.quizzes import Quiz, QuizQuestion
from tramplin.services.course_plans import CoursePlanService


@pytest.fixture(autouse=True)
def run_markdown_inline(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sandbox cannot wake asyncio from AnyIO worker threads; production still uses a worker."""

    async def run_sync(function: Any, *args: Any) -> Any:
        return function(*args)

    monkeypatch.setattr("tramplin.services.course_plans.to_thread.run_sync", run_sync)


class CourseRepo:
    def __init__(self) -> None:
        self.course: Course | None = None

    async def get_by_slug(self, slug: str, *, published_only: bool) -> Course | None:
        return self.course if self.course is not None and self.course.slug == slug else None

    def add(self, course: Course) -> Course:
        self.course = course
        return course


class ModuleRepo:
    def __init__(self) -> None:
        self.modules: list[Module] = []
        self.items: list[ModuleItem] = []

    def add(self, module: Module) -> Module:
        self.modules.append(module)
        return module

    def add_item(self, item: ModuleItem) -> ModuleItem:
        self.items.append(item)
        return item


class LessonRepo:
    def __init__(self) -> None:
        self.lessons: list[Lesson] = []

    def add(self, lesson: Lesson) -> Lesson:
        self.lessons.append(lesson)
        return lesson

    async def get_with_interview_cards(self, lesson_id: uuid.UUID) -> Lesson | None:
        return next((lesson for lesson in self.lessons if lesson.id == lesson_id), None)


class QuizRepo:
    def __init__(self) -> None:
        self.quizzes: list[Quiz] = []
        self.questions: list[QuizQuestion] = []

    def add(self, quiz: Quiz) -> Quiz:
        self.quizzes.append(quiz)
        return quiz

    def add_question(self, question: QuizQuestion) -> QuizQuestion:
        self.questions.append(question)
        return question


class AssetRepo:
    def __init__(self, assets: list[Asset] | None = None) -> None:
        self.assets = {asset.id: asset for asset in assets or []}

    async def get(self, asset_id: uuid.UUID) -> Asset | None:
        return self.assets.get(asset_id)


def make_service(
    assets: list[Asset] | None = None,
) -> tuple[CoursePlanService, FakeSession, CourseRepo, ModuleRepo, LessonRepo, QuizRepo]:
    transaction = FakeSession()
    courses = CourseRepo()
    modules = ModuleRepo()
    lessons = LessonRepo()
    quizzes = QuizRepo()
    service = CoursePlanService(
        transaction,
        cast(Any, courses),
        cast(Any, modules),
        cast(Any, lessons),
        cast(Any, quizzes),
        cast(Any, AssetRepo(assets)),
    )
    return service, transaction, courses, modules, lessons, quizzes


def course_plan(asset_id: uuid.UUID | None = None) -> CoursePlanApply:
    attachment_ids = [] if asset_id is None else [asset_id]
    return CoursePlanApply.model_validate(
        {
            "title": "Python",
            "slug": "python",
            "summary": "Курс",
            "color": "#3572a5",
            "est_hours": 8,
            "modules": [
                {
                    "title": "Основы",
                    "slug": "basics",
                    "lessons": [
                        {
                            "title": "Введение",
                            "slug": "intro",
                            "body_md": (
                                "# Введение\n\n"
                                ":::interview\n"
                                "Что такое Python?\n"
                                "---\n"
                                "Язык программирования.\n"
                                ":::"
                            ),
                            "est_minutes": 15,
                        }
                    ],
                    "quizzes": [
                        {
                            "title": "Проверка",
                            "slug": "check",
                            "lesson_slug": "intro",
                            "questions": [
                                {
                                    "position": 0,
                                    "prompt_md": "Выберите ответ",
                                    "type": "single",
                                    "options": [{"id": "a", "label": "A"}],
                                    "answer": {"value": "a"},
                                    "attachment_ids": attachment_ids,
                                }
                            ],
                        }
                    ],
                    "content_order": ["intro", "check"],
                }
            ],
        }
    )


async def test_apply_creates_and_then_updates_complete_course_plan() -> None:
    asset = Asset(s3_key="course/a.pdf", filename="a.pdf", mime=AssetMime.PDF, size=10)
    service, transaction, _, modules, lessons, quizzes = make_service([asset])
    actor_id = uuid.uuid7()

    course, created = await service.apply(course_plan(asset.id), actor_id)

    assert created.created == 5
    assert transaction.commits == 1
    assert course.status.value == "draft"
    assert len(lessons.lessons[0].interview_cards) == 1
    assert quizzes.questions[0].attachments == [asset]
    assert [item.position for item in modules.items] == [0, 1]

    course.modules = modules.modules
    lesson_item, quiz_item = modules.items
    lesson_item.lesson = lessons.lessons[0]
    quiz_item.quiz = quizzes.quizzes[0]
    updated_plan = course_plan(asset.id)
    updated_plan.title = "Python Pro"
    updated_plan.modules[0].lessons[0].body_md = "# Новое введение"
    updated_plan.modules[0].quizzes[0].questions[0].prompt_md = "Новый вопрос"

    updated_course, updated = await service.apply(updated_plan, actor_id)

    assert updated_course.title == "Python Pro"
    assert updated.updated == 3
    assert updated.unchanged == 2
    assert transaction.commits == 2
    assert lessons.lessons[0].body_html.startswith("<h1")


async def test_apply_repositions_module_left_out_of_a_later_plan() -> None:
    """A module already on the course but absent from a later plan call must be
    shifted out of the plan's position range, not left colliding with a new module
    inserted at the same position (regression for uq_modules_course_id_position)."""
    service, _, _, modules, *_ = make_service()
    actor_id = uuid.uuid7()

    course, _ = await service.apply(course_plan(), actor_id)
    course.modules = modules.modules
    basics = modules.modules[0]
    assert basics.position == 0

    second_plan = CoursePlanApply.model_validate(
        {
            "title": course.title,
            "slug": course.slug,
            "modules": [
                {
                    "title": "Продвинутое",
                    "slug": "advanced",
                    "lessons": [{"title": "Глубже", "slug": "deep", "body_md": "# Глубже"}],
                }
            ],
        }
    )

    await service.apply(second_plan, actor_id)

    advanced = next(module for module in modules.modules if module.slug == "advanced")
    assert advanced.position == 0
    assert basics.position == 1


async def test_apply_rejects_cross_module_lesson_link() -> None:
    service, transaction, *_ = make_service()
    plan = course_plan()
    plan.modules[0].quizzes[0].lesson_slug = "missing"

    with pytest.raises(InvalidQuizError):
        await service.apply(plan, uuid.uuid7())

    assert transaction.commits == 0


async def test_apply_rejects_duplicate_and_missing_attachments() -> None:
    asset_id = uuid.uuid7()
    service, _, *_ = make_service()
    duplicate = course_plan()
    duplicate.modules[0].quizzes[0].questions[0].attachment_ids = [asset_id, asset_id]

    with pytest.raises(InvalidQuizError):
        await service.apply(duplicate, uuid.uuid7())

    missing = course_plan(asset_id)
    with pytest.raises(NotFoundError):
        await service.apply(missing, uuid.uuid7())
