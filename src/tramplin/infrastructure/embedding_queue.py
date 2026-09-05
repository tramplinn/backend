import uuid_utils.compat as uuid
from faststream.rabbit import RabbitBroker, RabbitQueue

from tramplin.models.enums import RecommendationEntityType


class FastStreamEmbeddingQueue:
    def __init__(self, broker: RabbitBroker, queue: RabbitQueue) -> None:
        self._publisher = broker.publisher(
            queue,
            mandatory=True,
            persist=True,
        )

    async def publish(self, entity_type: RecommendationEntityType, entity_id: uuid.UUID) -> None:
        await self._publisher.publish(
            {"entity_type": entity_type.value, "entity_id": str(entity_id)},
            message_id=f"{entity_type.value}:{entity_id}",
        )
