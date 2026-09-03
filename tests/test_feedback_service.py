from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import pytest

from tests.fakes import FakeSession
from tramplin.core.errors import InvalidUpdateError, NotFoundError, UnprocessableError
from tramplin.models.assets import Asset
from tramplin.models.base import new_id
from tramplin.models.enums import AssetMime, FeedbackStatus
from tramplin.models.feedback import Feedback
from tramplin.services.feedback import MAX_ATTACHMENTS, MAX_MESSAGE, FeedbackService


def dependency(**values: Any) -> Any:
    return cast(Any, SimpleNamespace(**values))


def service(session: FakeSession, repository: Any, assets: Any = None) -> FeedbackService:
    return FeedbackService(
        session,
        repository,
        assets or dependency(get=AsyncMock(return_value=None)),
    )


def asset(owner_id: object) -> Asset:
    return Asset(
        filename="shot.png",
        s3_key="assets/shot.png",
        mime=AssetMime.PNG,
        size=1,
        created_by=owner_id,
    )


async def test_submit_trims_message_and_orders_owned_attachments() -> None:
    author_id = new_id()
    first, second = asset(author_id), asset(author_id)
    by_id = {first.id: first, second.id: second}
    session = FakeSession()
    repository = dependency(add=Mock())

    created = await service(
        session,
        repository,
        dependency(get=AsyncMock(side_effect=lambda asset_id: by_id.get(asset_id))),
    ).submit(
        "  Всё работает  ",
        author_id,
        page_path="/learning/course",
        attachment_ids=[second.id, first.id],
    )

    assert created.message == "Всё работает"
    assert created.author_id == author_id
    assert created.status is FeedbackStatus.NEW
    assert [item.asset_id for item in created.attachments] == [second.id, first.id]
    assert [item.position for item in created.attachments] == [0, 1]
    assert all(item.created_by == author_id for item in created.attachments)
    assert session.commits == 1
    repository.add.assert_called_once_with(created)


@pytest.mark.parametrize("message", ["   ", "x" * (MAX_MESSAGE + 1)])
async def test_submit_rejects_invalid_message(message: str) -> None:
    with pytest.raises(UnprocessableError):
        await service(FakeSession(), dependency(add=Mock())).submit(message, new_id())


async def test_submit_rejects_invalid_attachment_lists() -> None:
    attachment_id = new_id()
    editor = service(FakeSession(), dependency(add=Mock()))

    with pytest.raises(UnprocessableError):
        await editor.submit("message", new_id(), attachment_ids=[new_id()] * (MAX_ATTACHMENTS + 1))
    with pytest.raises(InvalidUpdateError):
        await editor.submit("message", new_id(), attachment_ids=[attachment_id, attachment_id])
    with pytest.raises(NotFoundError):
        await editor.submit("message", new_id(), attachment_ids=[attachment_id])


async def test_submit_rejects_another_users_asset() -> None:
    foreign_asset = asset(new_id())
    with pytest.raises(InvalidUpdateError):
        await service(
            FakeSession(),
            dependency(add=Mock()),
            dependency(get=AsyncMock(return_value=foreign_asset)),
        ).submit("message", new_id(), attachment_ids=[foreign_asset.id])


async def test_list_update_and_delete_pass_through() -> None:
    item = Feedback(author_id=new_id(), message="message", status=FeedbackStatus.NEW)
    session = FakeSession()
    repository = dependency(
        list=AsyncMock(return_value=([item], 1)),
        get=AsyncMock(return_value=item),
        delete=AsyncMock(),
    )
    editor = service(session, repository)

    page = await editor.list(status=FeedbackStatus.NEW, limit=5, offset=10)
    assert page.items == [item]
    assert (page.total, page.limit, page.offset) == (1, 5, 10)

    actor_id = new_id()
    updated = await editor.set_status(item.id, FeedbackStatus.RESOLVED, actor_id)
    assert updated.status is FeedbackStatus.RESOLVED
    assert updated.updated_by == actor_id

    await editor.delete(item.id)
    repository.delete.assert_awaited_once_with(item)
    assert session.commits == 2


async def test_unknown_feedback_is_not_found() -> None:
    repository = dependency(get=AsyncMock(return_value=None), delete=AsyncMock())
    editor = service(FakeSession(), repository)

    with pytest.raises(NotFoundError):
        await editor.set_status(new_id(), FeedbackStatus.RESOLVED, new_id())
    with pytest.raises(NotFoundError):
        await editor.delete(new_id())
