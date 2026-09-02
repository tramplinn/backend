from typing import Any, cast
from unittest.mock import AsyncMock, Mock

from tramplin.infrastructure.algorithm_queue import FastStreamSubmissionQueue
from tramplin.models.base import new_id


async def test_faststream_submission_queue_publishes_persistent_message() -> None:
    publisher = type("PublisherFake", (), {"publish": AsyncMock()})()
    broker = type("BrokerFake", (), {"publisher": Mock(return_value=publisher)})()
    queue = object()
    adapter = FastStreamSubmissionQueue(cast(Any, broker), cast(Any, queue))
    submission_id = new_id()

    await adapter.publish(submission_id)

    broker.publisher.assert_called_once_with(queue, mandatory=True, persist=True)
    publisher.publish.assert_awaited_once_with(
        {"submission_id": str(submission_id)},
        message_id=str(submission_id),
    )
