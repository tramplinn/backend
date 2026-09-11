from sqlalchemy import select

from tramplin.infrastructure.repositories.base import Repository
from tramplin.models.notifications import EmailJobOutbox


class EmailJobRepository(Repository):
    async def claim_outbox(self) -> EmailJobOutbox | None:
        stmt = (
            select(EmailJobOutbox)
            .where(EmailJobOutbox.dispatched_at.is_(None))
            .order_by(EmailJobOutbox.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        return (await self._session.scalars(stmt)).one_or_none()
