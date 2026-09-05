from collections.abc import Sequence
from typing import Protocol

import uuid_utils.compat as uuid

from tramplin.core.errors import InvalidUpdateError, NotFoundError, UnprocessableError
from tramplin.models.enums import FeedbackStatus
from tramplin.models.feedback import Feedback, FeedbackAttachment
from tramplin.services.assets import AssetRepositoryPort
from tramplin.services.contracts import PageResult, Transaction
from tramplin.services.entity_updates import mark_created, mark_updated, require

# В теле класса имя list занято методом FeedbackService.list.
type Attachments = list[FeedbackAttachment]

MAX_ATTACHMENTS = 5
MAX_MESSAGE = 4000


class FeedbackRepositoryPort(Protocol):
    async def list(
        self,
        *,
        status: FeedbackStatus | None,
        limit: int,
        offset: int,
    ) -> tuple[list[Feedback], int]: ...

    async def get(self, feedback_id: uuid.UUID) -> Feedback | None: ...

    def add(self, feedback: Feedback) -> Feedback: ...

    async def delete(self, feedback: Feedback) -> None: ...


class FeedbackService:
    def __init__(
        self,
        transaction: Transaction,
        feedback: FeedbackRepositoryPort,
        assets: AssetRepositoryPort,
    ) -> None:
        self._transaction = transaction
        self._feedback = feedback
        self._assets = assets

    async def list(
        self,
        *,
        status: FeedbackStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> PageResult[Feedback]:
        items, total = await self._feedback.list(status=status, limit=limit, offset=offset)
        return PageResult(items=items, total=total, limit=limit, offset=offset)

    async def submit(
        self,
        message: str,
        author_id: uuid.UUID,
        *,
        page_path: str | None = None,
        attachment_ids: Sequence[uuid.UUID] = (),
    ) -> Feedback:
        text = message.strip()
        if not text:
            raise UnprocessableError("Сообщение не может быть пустым")
        if len(text) > MAX_MESSAGE:
            raise UnprocessableError("Сообщение слишком длинное", max_length=MAX_MESSAGE)
        feedback = Feedback(
            author_id=author_id,
            message=text,
            page_path=page_path,
            status=FeedbackStatus.NEW,
        )
        feedback.attachments = await self._build_attachments(attachment_ids, author_id)
        mark_created(feedback, author_id)
        self._feedback.add(feedback)
        await self._transaction.commit()
        return feedback

    async def set_status(
        self,
        feedback_id: uuid.UUID,
        status: FeedbackStatus,
        actor_id: uuid.UUID,
    ) -> Feedback:
        feedback = require(
            await self._feedback.get(feedback_id), NotFoundError("Обращение не найдено")
        )
        feedback.status = status
        mark_updated(feedback, actor_id)
        await self._transaction.commit()
        return feedback

    async def delete(self, feedback_id: uuid.UUID) -> None:
        feedback = require(
            await self._feedback.get(feedback_id), NotFoundError("Обращение не найдено")
        )
        await self._feedback.delete(feedback)
        await self._transaction.commit()

    async def _build_attachments(
        self,
        asset_ids: Sequence[uuid.UUID],
        actor_id: uuid.UUID,
    ) -> Attachments:
        if len(asset_ids) > MAX_ATTACHMENTS:
            raise UnprocessableError("Слишком много вложений", max_attachments=MAX_ATTACHMENTS)
        if len(asset_ids) != len(set(asset_ids)):
            raise InvalidUpdateError("Вложения не должны повторяться", field="attachment_ids")
        attachments: Attachments = []
        for position, asset_id in enumerate(asset_ids):
            asset = require(await self._assets.get(asset_id), NotFoundError("Вложение не найдено"))
            if asset.created_by != actor_id:
                raise InvalidUpdateError("Можно прикреплять только собственные файлы")
            attachment = FeedbackAttachment(asset_id=asset.id, position=position)
            attachment.asset = asset
            mark_created(attachment, actor_id)
            attachments.append(attachment)
        return attachments
