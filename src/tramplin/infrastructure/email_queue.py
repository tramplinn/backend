from faststream.rabbit import RabbitBroker, RabbitQueue

from tramplin.models.enums import EmailQueue
from tramplin.services.contracts import EmailJobPayload


class FastStreamEmailQueue:
    def __init__(
        self,
        broker: RabbitBroker,
        transactional: RabbitQueue,
        bulk: RabbitQueue,
    ) -> None:
        self._publishers = {
            EmailQueue.TRANSACTIONAL: broker.publisher(transactional, mandatory=True, persist=True),
            EmailQueue.BULK: broker.publisher(bulk, mandatory=True, persist=True),
        }

    async def publish(self, payload: EmailJobPayload) -> None:
        await self._publishers[payload.queue].publish(
            {
                "message_id": str(payload.message_id),
                "category": payload.category,
                "to": payload.to_email,
                "subject": payload.subject,
                "html": payload.html_body,
                "text": payload.text_body,
            },
            message_id=str(payload.message_id),
        )
