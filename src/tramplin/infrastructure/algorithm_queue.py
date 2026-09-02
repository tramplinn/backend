import uuid_utils.compat as uuid
from faststream.rabbit import RabbitBroker, RabbitQueue


class FastStreamSubmissionQueue:
    def __init__(self, broker: RabbitBroker, queue: RabbitQueue) -> None:
        self._publisher = broker.publisher(
            queue,
            mandatory=True,
            persist=True,
        )

    async def publish(self, submission_id: uuid.UUID) -> None:
        await self._publisher.publish(
            {"submission_id": str(submission_id)},
            message_id=str(submission_id),
        )
