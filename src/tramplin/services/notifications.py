from typing import Protocol

from tramplin.core.time import utc_now
from tramplin.models.notifications import EmailJobOutbox
from tramplin.services.contracts import EmailJobPayload, EmailQueuePort, Transaction


class EmailJobRepositoryPort(Protocol):
    def add(self, job: EmailJobOutbox) -> EmailJobOutbox: ...

    async def claim_outbox(self) -> EmailJobOutbox | None: ...


class EmailDispatchService:
    """Тот же паттерн, что у AlgorithmDispatchService/EmbeddingDispatchService:
    воркер только релеит outbox в очередь, рендер уже сделан при записи строки."""

    def __init__(
        self,
        transaction: Transaction,
        jobs: EmailJobRepositoryPort,
        queue: EmailQueuePort,
    ) -> None:
        self._transaction = transaction
        self._jobs = jobs
        self._queue = queue

    async def dispatch_next(self) -> bool:
        job = await self._jobs.claim_outbox()
        if job is None:
            return False
        await self._queue.publish(
            EmailJobPayload(
                message_id=job.id,
                queue=job.queue,
                to_email=job.to_email,
                subject=job.subject,
                html_body=job.html_body,
                text_body=job.text_body,
                category=job.category,
            ),
        )
        job.dispatched_at = utc_now()
        job.attempts += 1
        job.last_error = None
        await self._transaction.commit()
        return True
