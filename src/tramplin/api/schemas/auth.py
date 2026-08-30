from datetime import datetime

from tramplin.api.schemas.base import ApiModel


class AuthorizeUrlOut(ApiModel):
    authorize_url: str


class AccessTokenOut(ApiModel):
    """Refresh-токен в теле не возвращается: он живёт только в httpOnly-куке."""

    access_token: str
    token_type: str = "Bearer"  # noqa: S105
    expires_at: datetime
