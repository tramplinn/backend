from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from tramplin.api.content_mapping import question_author_out, question_out
from tramplin.core.errors import InvalidQuizError
from tramplin.models.assets import Asset
from tramplin.models.base import new_id
from tramplin.models.content import Course, Lesson, Module, ModuleDep, ModuleItem
from tramplin.models.enums import AssetMime, ContentStatus, QuestionType
from tramplin.models.progress import LessonProgress, QuizAttempt
from tramplin.models.quizzes import Quiz, QuizQuestion
from tramplin.services.modules import has_dependency_path
from tramplin.services.progress import ProgressService
from tramplin.services.quiz_attempts import QuizAttemptService, evaluate_question
from tramplin.services.quizzes import validate_question


@pytest.mark.parametrize(
    ("question_type", "expected", "submitted", "correct"),
    [
        (QuestionType.SINGLE, {"value": "a"}, "a", True),
        (QuestionType.SINGLE, {"value": "a"}, "b", False),
        (QuestionType.MULTIPLE, {"values": ["a", "b"]}, ["b", "a"], True),
        (QuestionType.MULTIPLE, {"values": ["a", "b"]}, ["a"], False),
        (QuestionType.TEXT, {"accepted": ["PostgreSQL"]}, " postgresql ", True),
        (
            QuestionType.TEXT,
            {"accepted": ["PostgreSQL"], "case_sensitive": True},
            "postgresql",
            False,
        ),
        (
            QuestionType.MATCHING,
            {"pairs": {"left-1": "right-1"}},
            {"pairs": {"left-1": "right-1"}},
            True,
        ),
        (
            QuestionType.GROUPING,
            {"groups": {"item-1": "group-1"}},
            {"groups": {"item-1": "group-2"}},
            False,
        ),
        (QuestionType.FILE, {}, {"confirmed": True}, True),
    ],
)
def test_evaluate_question(
    question_type: QuestionType,
    expected: dict[str, object],
    submitted: object,
    correct: bool,
) -> None:
    question = QuizQuestion(
        quiz_id=None,
        prompt_md="Question",
        type=question_type,
        options_json=[],
        answer_json=expected,
    )

    assert evaluate_question(question, submitted).correct is correct


@pytest.mark.parametrize(
    ("question_type", "answer"),
    [
        (QuestionType.SINGLE, {}),
        (QuestionType.MULTIPLE, {"values": "not-a-list"}),
        (QuestionType.TEXT, {"accepted": []}),
        (QuestionType.MATCHING, {"pairs": {}}),
        (QuestionType.GROUPING, {"groups": {}}),
    ],
)
def test_invalid_answer_definition_is_rejected(
    question_type: QuestionType,
    answer: dict[str, object],
) -> None:
    with pytest.raises(InvalidQuizError):
        validate_question(question_type, [], answer)


def test_interactive_question_definitions_are_validated() -> None:
    validate_question(
        QuestionType.MATCHING,
        [
            {"kind": "left", "id": "left-1", "label": "HTTP"},
            {"kind": "right", "id": "right-1", "label": "протокол"},
        ],
        {"pairs": {"left-1": "right-1"}},
    )
    validate_question(
        QuestionType.GROUPING,
        [
            {"kind": "group", "id": "group-1", "label": "Backend"},
            {"kind": "item", "id": "item-1", "label": "Python"},
        ],
        {"groups": {"item-1": "group-1"}},
    )
    validate_question(QuestionType.FILE, [], {})


def test_public_question_dto_does_not_expose_answer() -> None:
    attachment = Asset(
        filename="task.pdf",
        s3_key="quiz/task.pdf",
        mime=AssetMime.PDF,
        size=10,
    )
    question = QuizQuestion(
        quiz_id=None,
        position=0,
        prompt_md="Question",
        type=QuestionType.SINGLE,
        options_json=["a", "b"],
        answer_json={"value": "a"},
        explain_md="Explanation",
    )
    question.attachments = [attachment]

    public = question_out(question, asset_base_url="https://assets.test").model_dump()
    author = question_author_out(question, asset_base_url="https://assets.test").model_dump()

    assert "answer" not in public
    assert public["attachments"][0]["url"] == "https://assets.test/quiz/task.pdf"
    assert author["answer"] == {"value": "a"}


def test_module_dependency_cycle_is_detected() -> None:
    first, second, third = new_id(), new_id(), new_id()
    edges = [
        ModuleDep(module_id=second, depends_on_id=first),
        ModuleDep(module_id=third, depends_on_id=second),
    ]

    assert has_dependency_path(edges, start=third, target=first)
    assert not has_dependency_path(edges, start=first, target=third)


class CourseServiceFake:
    def __init__(self, course: Course) -> None:
        self.course = course

    async def get(self, slug: str) -> Course:
        assert slug == self.course.slug
        return self.course


class LessonProgressRepositoryFake:
    def __init__(self, progress: list[LessonProgress]) -> None:
        self.progress = progress
        self.course_id: object | None = None

    async def list(
        self,
        user_id: object,
        *,
        course_id: object | None = None,
    ) -> list[LessonProgress]:
        self.course_id = course_id
        return self.progress


async def test_course_progress_aggregates_only_published_content() -> None:
    user_id = new_id()
    course = Course(title="Python", slug="python", status=ContentStatus.PUBLISHED)
    published_module = Module(
        course_id=course.id,
        title="Основы",
        slug="basics",
        position=0,
        status=ContentStatus.PUBLISHED,
    )
    draft_module = Module(
        course_id=course.id,
        title="Черновик",
        slug="draft",
        position=1,
        status=ContentStatus.DRAFT,
    )
    complete = Lesson(
        module_id=published_module.id,
        title="Готово",
        slug="done",
        status=ContentStatus.PUBLISHED,
    )
    pending = Lesson(
        module_id=published_module.id,
        title="В работе",
        slug="pending",
        status=ContentStatus.PUBLISHED,
    )
    draft = Lesson(
        module_id=published_module.id,
        title="Черновик",
        slug="draft",
        status=ContentStatus.DRAFT,
    )
    published_module.items = [
        ModuleItem(
            module_id=published_module.id, position=0, lesson_id=complete.id, lesson=complete
        ),
        ModuleItem(module_id=published_module.id, position=1, lesson_id=pending.id, lesson=pending),
        ModuleItem(module_id=published_module.id, position=2, lesson_id=draft.id, lesson=draft),
    ]
    draft_module.items = []
    course.modules = [published_module, draft_module]
    repository = LessonProgressRepositoryFake(
        [LessonProgress(user_id=user_id, lesson_id=complete.id)]
    )
    service = ProgressService(
        cast(Any, None),
        cast(Any, repository),
        cast(Any, None),
        cast(Any, None),
        cast(Any, CourseServiceFake(course)),
    )

    result = await service.course(user_id, "python")

    assert result.completed_lessons == 1
    assert result.total_lessons == 2
    assert len(result.modules) == 1
    assert result.modules[0].completed_lessons == 1
    assert repository.course_id == course.id


class TransactionFake:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1

    async def flush(self) -> None:
        pass


class QuizAttemptRepositoryFake:
    def __init__(self) -> None:
        self.attempts: list[QuizAttempt] = []

    def add(self, attempt: QuizAttempt) -> QuizAttempt:
        self.attempts.append(attempt)
        return attempt

    async def list(self, user_id: object, quiz_id: object) -> list[QuizAttempt]:
        return [
            attempt
            for attempt in self.attempts
            if attempt.user_id == user_id and attempt.quiz_id == quiz_id
        ]


class QuizServiceFake:
    def __init__(self, quiz: Quiz) -> None:
        self.quiz = quiz

    async def get(self, quiz_id: object) -> Quiz:
        assert quiz_id == self.quiz.id
        return self.quiz


async def test_quiz_attempt_service_submits_and_lists_attempts() -> None:
    user_id = new_id()
    quiz = Quiz(module_id=new_id(), title="Quiz", slug="quiz")
    question = QuizQuestion(
        quiz_id=quiz.id,
        position=0,
        prompt_md="Question",
        type=QuestionType.SINGLE,
        options_json=["a", "b"],
        answer_json={"value": "a"},
    )
    quiz.questions = [question]
    transaction = TransactionFake()
    repository = QuizAttemptRepositoryFake()
    service = QuizAttemptService(
        cast(Any, transaction),
        cast(Any, repository),
        cast(Any, QuizServiceFake(quiz)),
        cast(Any, SimpleNamespace(get=AsyncMock(return_value=None))),
    )

    result = await service.submit(user_id, quiz.id, {str(question.id): "a"})

    assert result.attempt.score == 1
    assert result.attempt.max_score == 1
    assert result.results[0].correct
    assert transaction.commits == 1
    assert await service.list(user_id, quiz.id) == [result.attempt]


async def test_quiz_attempt_service_rejects_empty_quiz() -> None:
    quiz = Quiz(module_id=new_id(), title="Quiz", slug="quiz")
    service = QuizAttemptService(
        cast(Any, TransactionFake()),
        cast(Any, QuizAttemptRepositoryFake()),
        cast(Any, QuizServiceFake(quiz)),
        cast(Any, SimpleNamespace(get=AsyncMock(return_value=None))),
    )

    with pytest.raises(InvalidQuizError, match="нет вопросов"):
        await service.submit(new_id(), quiz.id, {})


async def test_file_answer_must_belong_to_student_and_uses_self_check() -> None:
    user_id = new_id()
    quiz = Quiz(module_id=new_id(), title="Practice", slug="practice")
    question = QuizQuestion(
        quiz_id=quiz.id,
        prompt_md="Прикрепите результат",
        type=QuestionType.FILE,
        options_json=[],
        answer_json={},
    )
    quiz.questions = [question]
    asset = Asset(
        filename="answer.pdf",
        s3_key="answers/file.pdf",
        mime=AssetMime.PDF,
        size=10,
        created_by=user_id,
    )
    service = QuizAttemptService(
        cast(Any, TransactionFake()),
        cast(Any, QuizAttemptRepositoryFake()),
        cast(Any, QuizServiceFake(quiz)),
        cast(Any, SimpleNamespace(get=AsyncMock(return_value=asset))),
    )

    result = await service.submit(
        user_id,
        quiz.id,
        {str(question.id): {"asset_id": str(asset.id), "confirmed": True}},
    )

    assert result.results[0].correct
    asset.created_by = new_id()
    with pytest.raises(InvalidQuizError, match="другому пользователю"):
        await service.submit(
            user_id,
            quiz.id,
            {str(question.id): {"asset_id": str(asset.id), "confirmed": True}},
        )


@pytest.mark.parametrize(
    "answer",
    [
        {"accepted": "PostgreSQL"},
        {"accepted": ["PostgreSQL", 42]},
    ],
)
def test_malformed_text_answer_definition_is_never_graded_as_correct(
    answer: dict[str, object],
) -> None:
    question = QuizQuestion(
        quiz_id=None,
        position=0,
        prompt_md="Question",
        type=QuestionType.TEXT,
        options_json=[],
        answer_json=answer,
    )

    assert not evaluate_question(question, "PostgreSQL").correct


async def test_quiz_progress_marks_passed_only_on_full_score() -> None:
    """Правило «пройден» живёт на сервере: клиент его заново не выводит."""
    user_id = new_id()
    best = [
        QuizAttempt(user_id=user_id, quiz_id=new_id(), score=3, max_score=3),
        QuizAttempt(user_id=user_id, quiz_id=new_id(), score=2, max_score=3),
    ]
    service = ProgressService(
        cast(Any, None),
        cast(Any, None),
        cast(Any, SimpleNamespace(list_best=AsyncMock(return_value=best))),
        cast(Any, None),
        cast(Any, None),
    )

    result = await service.quizzes(user_id)

    assert [item.passed for item in result] == [True, False]
    assert [(item.score, item.max_score) for item in result] == [(3, 3), (2, 3)]
