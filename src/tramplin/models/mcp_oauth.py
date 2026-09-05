from datetime import datetime

import uuid_utils.compat as uuid
from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from tramplin.models.base import UUIDPrimaryKey


class McpOAuthAuthorization(UUIDPrimaryKey):
    __tablename__ = "mcp_oauth_authorizations"

    request_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    code_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    client_id: Mapped[str] = mapped_column(String(128))
    redirect_uri: Mapped[str] = mapped_column(String(512))
    state: Mapped[str] = mapped_column(String(512))
    code_challenge: Mapped[str] = mapped_column(String(128))
    scope: Mapped[str] = mapped_column(String(128))
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    request_expired_at: Mapped[datetime] = mapped_column(index=True)
    code_expired_at: Mapped[datetime | None]
    consumed_at: Mapped[datetime | None]


class McpOAuthToken(UUIDPrimaryKey):
    __tablename__ = "mcp_oauth_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    access_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    refresh_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    access_expired_at: Mapped[datetime] = mapped_column(index=True)
    refresh_expired_at: Mapped[datetime] = mapped_column(index=True)
    revoked_at: Mapped[datetime | None]
