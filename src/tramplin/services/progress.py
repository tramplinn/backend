from dataclasses import dataclass
from typing import Protocol

import uuid_utils.compat as uuid

from tramplin.models.enums import ContentStatus
from tramplin.models.progress import LessonProgress, QuizAttempt
from tramplin.services.contracts import Transaction
from tramplin.services.courses import CourseService
from tramplin.services.lessons import LessonService


class LessonProgressRepositoryPort(Protocol):
    async def get(
        self,
        user_id: uuid.UUID,
        lesson_id: uuid.UUID,
    ) -> LessonProgress | None: ...

    async def list(
        self,
        user_id: uuid.UUID,
        *,
        course_id: uuid.UUID | None = None,
    ) -> list[LessonProgress]: ...

    def add(self, progress: LessonProgress) -> LessonProgress: ...

    async def delete_for_lesson(self, user_id: uuid.UUID, lesson_id: uuid.UUID) -> None: ...


class QuizAttemptRepositoryPort(Protocol):
    async def list_best(self, user_id: uuid.UUID) -> list[QuizAttempt]: ...


@dataclass(frozen=True, slots=True)
class QuizProgressResult:
    quiz_id: uuid.UUID
    score: int
    max_score: int
    passed: bool


@dataclass(frozen=True, slots=True)
class ModuleProgressResult:
    module_id: uuid.UUID
    completed_lessons: int
    total_lessons: int


@dataclass(frozen=True, slots=True)
class CourseProgressResult:
    course_id: uuid.UUID
    completed_lessons: int
    total_lessons: int
    modules: list[ModuleProgressResult]


class ProgressService:
    def __init__(
        self,
        transaction: Transaction,
        progress: LessonProgressRepositoryPort,
        attempts: QuizAttemptRepositoryPort,
        lessons: LessonService,
        courses: CourseService,
    ) -> None:
        self._transaction = transaction
        self._progress = progress
        self._attempts = attempts
        self._lessons = lessons
        self._courses = courses

    async def lessons(self, user_id: uuid.UUID) -> list[LessonProgress]:
        return await self._progress.list(user_id)

    async def quizzes(self, user_id: uuid.UUID) -> list[QuizProgressResult]:
        """Тест считается пройденным при максимальном балле: правило про оценку
        живёт на сервере, клиент его не выводит заново."""
        return [
            QuizProgressResult(
                quiz_id=attempt.quiz_id,
                score=attempt.score,
                max_score=attempt.max_score,
                passed=attempt.score == attempt.max_score,
            )
            for attempt in await self._attempts.list_best(user_id)
        ]

    async def course(self, user_id: uuid.UUID, course_slug: str) -> CourseProgressResult:
        course = await self._courses.get(course_slug)
        completed_ids = {
            progress.lesson_id
            for progress in await self._progress.list(user_id, course_id=course.id)
        }
        modules = []
        for module in sorted(course.modules, key=lambda item: item.position):
            if module.status is not ContentStatus.PUBLISHED:
                continue
            lessons = [
                item.lesson
                for item in module.items
                if item.lesson is not None and item.lesson.status is ContentStatus.PUBLISHED
            ]
            modules.append(
                ModuleProgressResult(
                    module_id=module.id,
                    completed_lessons=sum(lesson.id in completed_ids for lesson in lessons),
                    total_lessons=len(lessons),
                ),
            )
        return CourseProgressResult(
            course_id=course.id,
            completed_lessons=sum(module.completed_lessons for module in modules),
            total_lessons=sum(module.total_lessons for module in modules),
            modules=modules,
        )

    async def complete(self, user_id: uuid.UUID, lesson_id: uuid.UUID) -> LessonProgress:
        await self._lessons.get(lesson_id)
        existing = await self._progress.get(user_id, lesson_id)
        if existing is not None:
            return existing
        progress = self._progress.add(
            LessonProgress(
                user_id=user_id,
                lesson_id=lesson_id,
                created_by=user_id,
                updated_by=user_id,
            ),
        )
        await self._transaction.commit()
        return progress

    async def reopen(self, user_id: uuid.UUID, lesson_id: uuid.UUID) -> None:
        await self._progress.delete_for_lesson(user_id, lesson_id)
        await self._transaction.commit()
