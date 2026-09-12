from tramplin.core.time import utc_now
from tramplin.services.algorithm_ports import AlgorithmDispatchRepositoryPort
from tramplin.services.contracts import SubmissionQueue, Transaction


class AlgorithmDispatchService:
    def __init__(
        self,
        transaction: Transaction,
        algorithms: AlgorithmDispatchRepositoryPort,
        queue: SubmissionQueue,
    ) -> None:
        self._transaction = transaction
        self._algorithms = algorithms
        self._queue = queue

    async def dispatch_next(self) -> bool:
        event = await self._algorithms.claim_outbox()
        if event is None:
            return False
        await self._queue.publish(event.submission_id)
        event.dispatched_at = utc_now()
        event.attempts += 1
        event.last_error = None
        await self._transaction.commit()
        return True
