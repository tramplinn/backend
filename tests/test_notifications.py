import uuid_utils.compat as uuid

from tramplin.models.enums import EmailQueue
from tramplin.models.notifications import EmailJobOutbox
from tramplin.services.contracts import EmailJobPayload
from tramplin.services.notifications import EmailDispatchService


class TransactionFake:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1

    async def flush(self) -> None:
        pass


class EmailJobRepoFake:
    def __init__(self) -> None:
        self.jobs: dict[uuid.UUID, EmailJobOutbox] = {}

    def add(self, job: EmailJobOutbox) -> EmailJobOutbox:
        self.jobs[job.id] = job
        return job

    async def claim_outbox(self) -> EmailJobOutbox | None:
        return next((job for job in self.jobs.values() if job.dispatched_at is None), None)


class EmailQueueFake:
    def __init__(self) -> None:
        self.published: list[EmailJobPayload] = []

    async def publish(self, payload: EmailJobPayload) -> None:
        self.published.append(payload)


def _job() -> EmailJobOutbox:
    return EmailJobOutbox(
        to_email="student@example.com",
        subject="Код для входа: 482913",
        html_body="<p>482913</p>",
        text_body="482913",
        category="auth_otp",
        queue=EmailQueue.TRANSACTIONAL,
        dispatched_at=None,
        attempts=0,
        last_error="old",
    )


async def test_email_dispatch_service_dispatches_once() -> None:
    repo = EmailJobRepoFake()
    job = _job()
    repo.jobs[job.id] = job
    tx = TransactionFake()
    queue = EmailQueueFake()
    dispatch = EmailDispatchService(tx, repo, queue)

    assert await dispatch.dispatch_next()
    assert queue.published == [
        EmailJobPayload(
            message_id=job.id,
            queue=EmailQueue.TRANSACTIONAL,
            to_email="student@example.com",
            subject="Код для входа: 482913",
            html_body="<p>482913</p>",
            text_body="482913",
            category="auth_otp",
        )
    ]
    assert job.dispatched_at is not None
    assert job.attempts == 1
    assert job.last_error is None
    assert tx.commits == 1
    assert not await dispatch.dispatch_next()
