import uuid_utils.compat as uuid

from tramplin.api.schemas.base import ApiModel


class TagOut(ApiModel):
    id: uuid.UUID
    name: str
