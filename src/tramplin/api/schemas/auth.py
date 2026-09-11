from datetime import datetime

from pydantic import EmailStr, Field

from tramplin.api.schemas.base import ApiModel
from tramplin.models.enums import IdentityProvider


class AuthorizeUrlOut(ApiModel):
    authorize_url: str


class EmailStartIn(ApiModel):
    email: EmailStr


class EmailVerifyIn(ApiModel):
    email: EmailStr
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class ProvidersOut(ApiModel):
    providers: list[IdentityProvider] = Field(default_factory=list)


class AccessTokenOut(ApiModel):
    """Refresh-токен в теле не возвращается: он живёт только в httpOnly-куке."""

    access_token: str
    token_type: str = "Bearer"  # noqa: S105
    expires_at: datetime


class McpAuthorizationRequestOut(ApiModel):
    client_name: str
    scope: str


class McpAuthorizationApprovalOut(ApiModel):
    redirect_url: str


class McpIntrospectionOut(ApiModel):
    active: bool = True
    sub: str
    login: str
    role: str
    scope: str = "authoring"
