import uuid_utils.compat as uuid

from tramplin.api.schemas.base import ApiModel


class PublishSkipOut(ApiModel):
    id: uuid.UUID
    kind: str
    title: str
    reason: str


class PublishReportOut(ApiModel):
    published: list[uuid.UUID]
    skipped: list[PublishSkipOut]
