import uuid_utils.compat as uuid
from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from tramplin.infrastructure.repositories.base import Repository
from tramplin.models.base import soft_delete
from tramplin.models.content import Course, Lesson, Module
from tramplin.models.enums import ContentStatus
from tramplin.models.quizzes import Quiz, QuizQuestion


class QuizRepository(Repository):
    async def get(self, quiz_id: uuid.UUID, *, published_only: bool) -> Quiz | None:
        stmt = (
            select(Quiz)
            .join(Module, Quiz.module_id == Module.id)
            .join(Course, Module.course_id == Course.id)
            .outerjoin(Lesson, Quiz.lesson_id == Lesson.id)
            .where(Quiz.id == quiz_id)
            .options(selectinload(Quiz.questions).selectinload(QuizQuestion.attachments))
        )
        if published_only:
            stmt = stmt.where(
                Quiz.status == ContentStatus.PUBLISHED,
                Module.status == ContentStatus.PUBLISHED,
                Course.status == ContentStatus.PUBLISHED,
                or_(Quiz.lesson_id.is_(None), Lesson.status == ContentStatus.PUBLISHED),
            )
        return (await self._session.scalars(stmt)).one_or_none()

    def add(self, quiz: Quiz) -> Quiz:
        self._session.add(quiz)
        return quiz

    async def delete(self, quiz: Quiz) -> None:
        soft_delete(quiz)

    async def get_question(self, question_id: uuid.UUID) -> QuizQuestion | None:
        stmt = (
            select(QuizQuestion)
            .where(QuizQuestion.id == question_id)
            .options(selectinload(QuizQuestion.attachments))
        )
        return (await self._session.scalars(stmt)).one_or_none()

    def add_question(self, question: QuizQuestion) -> QuizQuestion:
        self._session.add(question)
        return question

    async def delete_question(self, question: QuizQuestion) -> None:
        await self._session.delete(question)
