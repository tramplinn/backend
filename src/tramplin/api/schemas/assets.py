import uuid_utils.compat as uuid

from tramplin.api.schemas.base import ApiModel
from tramplin.models.enums import AssetMime


class AssetOut(ApiModel):
    id: uuid.UUID
    filename: str
    mime: AssetMime
    size: int
    url: str
