import json
from dataclasses import dataclass
from typing import Any, Protocol

import uuid_utils.compat as uuid

from tramplin.core.errors import InvalidQuizError
from tramplin.models.assets import Asset
from tramplin.models.enums import QuestionType
from tramplin.models.progress import QuizAttempt
from tramplin.models.quizzes import QuizQuestion
from tramplin.services.assets import AssetRepositoryPort
from tramplin.services.contracts import Transaction
from tramplin.services.quizzes import QuizService


class QuizAttemptRepositoryPort(Protocol):
    def add(self, attempt: QuizAttempt) -> QuizAttempt: ...

    async def list(self, user_id: uuid.UUID, quiz_id: uuid.UUID) -> list[QuizAttempt]: ...


@dataclass(frozen=True, slots=True)
class QuestionResult:
    question_id: uuid.UUID
    correct: bool
    explanation: str | None


@dataclass(frozen=True, slots=True)
class AttemptResult:
    attempt: QuizAttempt
    results: list[QuestionResult]


class QuizAttemptService:
    def __init__(
        self,
        transaction: Transaction,
        attempts: QuizAttemptRepositoryPort,
        quizzes: QuizService,
        assets: AssetRepositoryPort,
    ) -> None:
        self._transaction = transaction
        self._attempts = attempts
        self._quizzes = quizzes
        self._assets = assets

    async def submit(
        self,
        user_id: uuid.UUID,
        quiz_id: uuid.UUID,
        answers: dict[str, Any],
    ) -> AttemptResult:
        quiz = await self._quizzes.get(quiz_id)
        if not quiz.questions:
            raise InvalidQuizError("В тесте нет вопросов")
        for question in quiz.questions:
            if question.type is QuestionType.FILE:
                await self._validate_file_answer(user_id, answers.get(str(question.id)))
        results = [
            evaluate_question(question, answers.get(str(question.id)))
            for question in quiz.questions
        ]
        attempt = self._attempts.add(
            QuizAttempt(
                user_id=user_id,
                quiz_id=quiz.id,
                score=sum(result.correct for result in results),
                max_score=len(results),
                answers_json=answers,
                created_by=user_id,
                updated_by=user_id,
            ),
        )
        await self._transaction.commit()
        return AttemptResult(attempt=attempt, results=results)

    async def list(self, user_id: uuid.UUID, quiz_id: uuid.UUID) -> list[QuizAttempt]:
        await self._quizzes.get(quiz_id)
        return await self._attempts.list(user_id, quiz_id)

    async def _validate_file_answer(self, user_id: uuid.UUID, submitted: Any) -> Asset:
        if not isinstance(submitted, dict):
            raise InvalidQuizError("К файловому заданию нужно прикрепить файл")
        try:
            asset_id = uuid.UUID(submitted["asset_id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidQuizError("Некорректный файл ответа") from exc
        asset = await self._assets.get(asset_id)
        if asset is None or asset.created_by != user_id:
            raise InvalidQuizError("Файл ответа не найден или принадлежит другому пользователю")
        return asset


def evaluate_question(question: QuizQuestion, submitted: Any) -> QuestionResult:
    """Сравнивает ответ студента с сохранённым ответом без раскрытия последнего."""
    expected = question.answer_json
    if question.type is QuestionType.SINGLE:
        correct = submitted == expected.get("value")
    elif question.type is QuestionType.MULTIPLE:
        correct = isinstance(submitted, list) and _canonical_values(submitted) == _canonical_values(
            expected.get("values", []),
        )
    elif question.type is QuestionType.TEXT:
        correct = _text_matches(submitted, expected)
    elif question.type is QuestionType.MATCHING:
        correct = _mapping_matches(submitted, expected, "pairs")
    elif question.type is QuestionType.GROUPING:
        correct = _mapping_matches(submitted, expected, "groups")
    else:
        correct = isinstance(submitted, dict) and submitted.get("confirmed") is True
    return QuestionResult(question.id, correct, question.explain_md)


def _canonical_values(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    return sorted(json.dumps(value, sort_keys=True, ensure_ascii=False) for value in values)


def _text_matches(submitted: Any, expected: dict[str, Any]) -> bool:
    accepted = expected.get("accepted")
    if not isinstance(submitted, str) or not isinstance(accepted, list):
        return False
    if not all(isinstance(value, str) for value in accepted):
        return False

    case_sensitive = expected.get("case_sensitive") is True
    actual = submitted.strip()
    normalized = (value.strip() for value in accepted)
    if case_sensitive:
        return actual in normalized
    return actual.casefold() in (value.casefold() for value in normalized)


def _mapping_matches(submitted: Any, expected: dict[str, Any], key: str) -> bool:
    if not isinstance(submitted, dict):
        return False
    actual = submitted.get(key)
    wanted = expected.get(key)
    return isinstance(actual, dict) and isinstance(wanted, dict) and actual == wanted
