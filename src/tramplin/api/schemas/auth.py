from datetime import datetime

from pydantic import Field

from tramplin.api.schemas.base import ApiModel
from tramplin.models.enums import IdentityProvider


class AuthorizeUrlOut(ApiModel):
    authorize_url: str


class ProvidersOut(ApiModel):
    providers: list[IdentityProvider] = Field(default_factory=list)


class AccessTokenOut(ApiModel):
    """Refresh-токен в теле не возвращается: он живёт только в httpOnly-куке."""

    access_token: str
    token_type: str = "Bearer"  # noqa: S105
    expires_at: datetime
