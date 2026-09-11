from typing import Any, cast
from unittest.mock import AsyncMock, Mock

from tramplin.infrastructure.email_queue import FastStreamEmailQueue
from tramplin.models.base import new_id
from tramplin.models.enums import EmailQueue
from tramplin.services.contracts import EmailJobPayload


def _payload(queue: EmailQueue) -> EmailJobPayload:
    return EmailJobPayload(
        message_id=new_id(),
        queue=queue,
        to_email="student@example.com",
        subject="Код для входа: 482913",
        html_body="<p>482913</p>",
        text_body="482913",
        category="auth_otp",
    )


async def test_publishes_to_the_queue_matching_payload_priority() -> None:
    transactional_publisher = type("PublisherFake", (), {"publish": AsyncMock()})()
    bulk_publisher = type("PublisherFake", (), {"publish": AsyncMock()})()
    broker = type(
        "BrokerFake", (), {"publisher": Mock(side_effect=[transactional_publisher, bulk_publisher])}
    )()
    transactional_queue = object()
    bulk_queue = object()

    adapter = FastStreamEmailQueue(
        cast(Any, broker), cast(Any, transactional_queue), cast(Any, bulk_queue)
    )

    payload = _payload(EmailQueue.TRANSACTIONAL)
    await adapter.publish(payload)

    transactional_publisher.publish.assert_awaited_once_with(
        {
            "message_id": str(payload.message_id),
            "category": "auth_otp",
            "to": "student@example.com",
            "subject": "Код для входа: 482913",
            "html": "<p>482913</p>",
            "text": "482913",
        },
        message_id=str(payload.message_id),
    )
    bulk_publisher.publish.assert_not_called()

    await adapter.publish(_payload(EmailQueue.BULK))
    bulk_publisher.publish.assert_awaited_once()
    assert transactional_publisher.publish.await_count == 1
