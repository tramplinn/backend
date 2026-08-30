import uuid_utils.compat as uuid
from sqlalchemy import func, select
from sqlalchemy.orm import aliased

from tramplin.infrastructure.repositories.base import Repository
from tramplin.models.progress import QuizAttempt


class QuizAttemptRepository(Repository):
    def add(self, attempt: QuizAttempt) -> QuizAttempt:
        self._session.add(attempt)
        return attempt

    async def list_best(self, user_id: uuid.UUID) -> list[QuizAttempt]:
        """По одной строке на тест — с наибольшим результатом пользователя."""
        ranked = (
            select(
                QuizAttempt,
                func.row_number()
                .over(
                    partition_by=QuizAttempt.quiz_id,
                    order_by=(QuizAttempt.score.desc(), QuizAttempt.id.desc()),
                )
                .label("rank"),
            )
            .where(QuizAttempt.user_id == user_id)
            .subquery()
        )
        best = aliased(QuizAttempt, ranked)
        stmt = select(best).where(ranked.c.rank == 1)
        return list(await self._session.scalars(stmt))

    async def list(self, user_id: uuid.UUID, quiz_id: uuid.UUID) -> list[QuizAttempt]:
        stmt = (
            select(QuizAttempt)
            .where(QuizAttempt.user_id == user_id, QuizAttempt.quiz_id == quiz_id)
            .order_by(QuizAttempt.id.desc())
        )
        return list(await self._session.scalars(stmt))
