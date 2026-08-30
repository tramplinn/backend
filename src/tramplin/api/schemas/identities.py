from datetime import datetime

from tramplin.api.schemas.base import ApiModel
from tramplin.models.enums import IdentityProvider


class IdentityOut(ApiModel):
    provider: IdentityProvider
    provider_id: str
    email: str | None
    created_at: datetime
