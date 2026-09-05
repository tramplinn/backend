import uuid_utils.compat as uuid
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from tramplin.infrastructure.repositories.base import Repository
from tramplin.models.enums import FeedbackStatus
from tramplin.models.feedback import Feedback, FeedbackAttachment


class FeedbackRepository(Repository):
    _related = (
        selectinload(Feedback.attachments).selectinload(FeedbackAttachment.asset),
        selectinload(Feedback.author),
    )

    async def list(
        self,
        *,
        status: FeedbackStatus | None,
        limit: int,
        offset: int,
    ) -> tuple[list[Feedback], int]:
        stmt = select(Feedback).options(*self._related)
        count_stmt = select(func.count()).select_from(Feedback)
        if status is not None:
            stmt = stmt.where(Feedback.status == status)
            count_stmt = count_stmt.where(Feedback.status == status)
        total = await self._session.scalar(count_stmt)
        stmt = stmt.order_by(Feedback.created_at.desc(), Feedback.id.desc())
        items = await self._session.scalars(stmt.limit(limit).offset(offset))
        return list(items), total or 0

    async def get(self, feedback_id: uuid.UUID) -> Feedback | None:
        stmt = select(Feedback).where(Feedback.id == feedback_id).options(*self._related)
        return (await self._session.scalars(stmt)).one_or_none()
