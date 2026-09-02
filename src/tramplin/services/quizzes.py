from collections.abc import Sequence
from typing import Any, Protocol

import uuid_utils.compat as uuid

from tramplin.core.errors import InvalidQuizError, NotFoundError
from tramplin.models.assets import Asset
from tramplin.models.content import Lesson
from tramplin.models.enums import ContentStatus, QuestionType
from tramplin.models.quizzes import Quiz, QuizQuestion
from tramplin.services.assets import AssetRepositoryPort
from tramplin.services.contracts import Transaction
from tramplin.services.entity_updates import mark_created, mark_updated, validate_required_updates
from tramplin.services.lessons import LessonRepositoryPort
from tramplin.services.modules import ModuleRepositoryPort, next_module_item


class QuizRepositoryPort(Protocol):
    async def get(self, quiz_id: uuid.UUID, *, published_only: bool) -> Quiz | None: ...

    def add(self, quiz: Quiz) -> Quiz: ...

    async def delete(self, quiz: Quiz) -> None: ...

    async def get_question(self, question_id: uuid.UUID) -> QuizQuestion | None: ...

    def add_question(self, question: QuizQuestion) -> QuizQuestion: ...

    async def delete_question(self, question: QuizQuestion) -> None: ...


class QuizService:
    def __init__(
        self,
        transaction: Transaction,
        quizzes: QuizRepositoryPort,
        modules: ModuleRepositoryPort,
        lessons: LessonRepositoryPort,
        assets: AssetRepositoryPort,
    ) -> None:
        self._transaction = transaction
        self._quizzes = quizzes
        self._modules = modules
        self._lessons = lessons
        self._assets = assets

    async def get(self, quiz_id: uuid.UUID, *, published_only: bool = True) -> Quiz:
        quiz = await self._quizzes.get(quiz_id, published_only=published_only)
        if quiz is None:
            raise NotFoundError("Тест не найден")
        return quiz

    async def create(self, module_id: uuid.UUID, quiz: Quiz, actor_id: uuid.UUID) -> Quiz:
        if await self._modules.get_for_update(module_id) is None:
            raise NotFoundError("Модуль не найден")
        await self._ensure_lesson_in_module(quiz.lesson_id, module_id)
        if quiz.status is ContentStatus.PUBLISHED:
            raise InvalidQuizError("Сначала добавьте вопросы, затем опубликуйте тест")
        quiz.module_id = module_id
        # Вопросов у нового теста нет, но коллекция не помечена загруженной:
        # после commit quiz_out ушёл бы в ленивую подгрузку вне greenlet-контекста.
        quiz.questions = []
        mark_created(quiz, actor_id)
        self._quizzes.add(quiz)
        await self._append_to_module(module_id, actor_id, quiz)
        await self._transaction.commit()
        return quiz

    async def update(
        self, quiz_id: uuid.UUID, changes: dict[str, Any], actor_id: uuid.UUID
    ) -> Quiz:
        quiz = await self.get(quiz_id, published_only=False)
        lesson_id = changes.get("lesson_id", quiz.lesson_id)
        await self._ensure_lesson_in_module(lesson_id, quiz.module_id)
        if changes.get("status") is ContentStatus.PUBLISHED and not quiz.questions:
            raise InvalidQuizError("Нельзя опубликовать тест без вопросов")
        validate_required_updates(changes, {"title", "slug", "status"})
        quiz.title = changes.get("title", quiz.title)
        quiz.slug = changes.get("slug", quiz.slug)
        quiz.lesson_id = changes.get("lesson_id", quiz.lesson_id)
        quiz.status = changes.get("status", quiz.status)
        mark_updated(quiz, actor_id)
        await self._transaction.commit()
        return quiz

    async def _append_to_module(
        self,
        module_id: uuid.UUID,
        actor_id: uuid.UUID,
        quiz: Quiz,
    ) -> None:
        """Место в ленте — единственное хранилище порядка, заводим сразу."""
        items = await self._modules.list_items(module_id)
        self._modules.add_item(
            next_module_item(
                items,
                module_id=module_id,
                actor_id=actor_id,
                quiz_id=quiz.id,
            )
        )

    async def delete(self, quiz_id: uuid.UUID) -> None:
        quiz = await self.get(quiz_id, published_only=False)
        await self._quizzes.delete(quiz)
        await self._transaction.commit()

    async def create_question(
        self,
        quiz_id: uuid.UUID,
        question: QuizQuestion,
        actor_id: uuid.UUID,
        attachment_ids: Sequence[uuid.UUID] = (),
    ) -> QuizQuestion:
        quiz = await self.get(quiz_id, published_only=False)
        validate_question(
            question.type,
            question.options_json,
            question.answer_json,
        )
        question.quiz_id = quiz.id
        question.attachments = await self._resolve_attachments(attachment_ids)
        mark_created(question, actor_id)
        self._quizzes.add_question(question)
        await self._transaction.commit()
        return question

    async def update_question(
        self,
        question_id: uuid.UUID,
        changes: dict[str, Any],
        actor_id: uuid.UUID,
    ) -> QuizQuestion:
        question = await self._quizzes.get_question(question_id)
        if question is None:
            raise NotFoundError("Вопрос не найден")
        question_type = changes.get("type", question.type)
        options = changes.get("options_json", question.options_json)
        answer = changes.get("answer_json", question.answer_json)
        validate_question(question_type, options, answer)
        attachment_ids = changes.pop("attachment_ids", None)
        if attachment_ids is not None:
            question.attachments = await self._resolve_attachments(attachment_ids)
        validate_required_updates(
            changes,
            {"position", "prompt_md", "type", "options_json", "answer_json"},
        )
        question.position = changes.get("position", question.position)
        question.prompt_md = changes.get("prompt_md", question.prompt_md)
        question.type = changes.get("type", question.type)
        question.options_json = changes.get("options_json", question.options_json)
        question.answer_json = changes.get("answer_json", question.answer_json)
        question.explain_md = changes.get("explain_md", question.explain_md)
        mark_updated(question, actor_id)
        await self._transaction.commit()
        return question

    async def delete_question(self, question_id: uuid.UUID) -> None:
        question = await self._quizzes.get_question(question_id)
        if question is None:
            raise NotFoundError("Вопрос не найден")
        await self._quizzes.delete_question(question)
        await self._transaction.commit()

    async def _ensure_lesson_in_module(
        self, lesson_id: uuid.UUID | None, module_id: uuid.UUID
    ) -> None:
        if lesson_id is None:
            return
        lesson: Lesson | None = await self._lessons.get(lesson_id, published_only=False)
        if lesson is None or lesson.module_id != module_id:
            raise InvalidQuizError("Урок теста должен принадлежать выбранному модулю")

    async def _resolve_attachments(self, asset_ids: Sequence[uuid.UUID]) -> list[Asset]:
        if len(asset_ids) != len(set(asset_ids)):
            raise InvalidQuizError("Прикреплённые файлы не должны повторяться")
        assets: list[Asset] = []
        for asset_id in asset_ids:
            asset = await self._assets.get(asset_id)
            if asset is None:
                raise NotFoundError("Прикреплённый файл не найден")
            assets.append(asset)
        return assets


def validate_question(
    question_type: QuestionType,
    options: list[Any],
    answer: dict[str, Any],
) -> None:
    """Проверяет внутренний формат правильного ответа перед сохранением вопроса."""
    if question_type is QuestionType.SINGLE and "value" in answer:
        return
    if question_type is QuestionType.MULTIPLE and isinstance(answer.get("values"), list):
        return
    if question_type is QuestionType.TEXT:
        accepted = answer.get("accepted")
        if (
            isinstance(accepted, list)
            and accepted
            and all(isinstance(item, str) for item in accepted)
        ):
            return
    if question_type is QuestionType.MATCHING and _valid_mapping(options, answer, "pairs"):
        return
    if question_type is QuestionType.GROUPING and _valid_mapping(options, answer, "groups"):
        return
    if question_type is QuestionType.FILE and not answer:
        return
    raise InvalidQuizError(f"Неверный формат ответа для типа {question_type.value}")


def _valid_mapping(options: list[Any], answer: dict[str, Any], key: str) -> bool:
    mapping = answer.get(key)
    if not isinstance(mapping, dict) or not mapping:
        return False
    source_kind = "left" if key == "pairs" else "item"
    target_kind = "right" if key == "pairs" else "group"
    source_ids = _option_ids(options, source_kind)
    target_ids = _option_ids(options, target_kind)
    sources = set(source_ids)
    targets = set(target_ids)
    if (
        not sources
        or not targets
        or len(source_ids) != len(sources)
        or len(target_ids) != len(targets)
        or len(source_ids) + len(target_ids) != len(options)
        or set(mapping) != sources
    ):
        return False
    values = list(mapping.values())
    if not all(isinstance(value, str) and value in targets for value in values):
        return False
    return key != "pairs" or len(values) == len(set(values)) == len(targets)


def _option_ids(options: list[Any], kind: str) -> list[str]:
    return [
        item["id"]
        for item in options
        if isinstance(item, dict)
        and item.get("kind") == kind
        and isinstance(item.get("id"), str)
        and isinstance(item.get("label"), str)
        and item["id"]
        and item["label"]
    ]
