from datetime import datetime

import uuid_utils.compat as uuid
from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from tramplin.models.base import UUIDPrimaryKey
from tramplin.models.enums import IdentityProvider, UserRole


class User(UUIDPrimaryKey):
    __tablename__ = "users"

    login: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str | None] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(320), unique=True)
    avatar_url: Mapped[str | None] = mapped_column(String(512))
    student_number: Mapped[str | None] = mapped_column(String(32), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean(), default=True, server_default="true")
    password_hash: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(
        default=UserRole.STUDENT,
        server_default=UserRole.STUDENT.value,
    )

    identities: Mapped[list[UserIdentity]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        foreign_keys="UserIdentity.user_id",
    )


class UserIdentity(UUIDPrimaryKey):
    """Способ входа. Связывание по email запрещено — только явным действием пользователя."""

    __tablename__ = "user_identities"
    __table_args__ = (
        UniqueConstraint("provider", "provider_id", name="uq_user_identities_provider_provider_id"),
        UniqueConstraint("user_id", "provider", name="uq_user_identities_user_id_provider"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    provider: Mapped[IdentityProvider]
    provider_id: Mapped[str] = mapped_column(String(128))
    email: Mapped[str | None] = mapped_column(String(320))

    user: Mapped[User] = relationship(back_populates="identities", foreign_keys=[user_id])


class RefreshToken(UUIDPrimaryKey):
    """Хранится только sha256-хэш токена; сырое значение живёт в куке браузера."""

    __tablename__ = "refresh_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    expired_at: Mapped[datetime]
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)

    user: Mapped[User] = relationship(foreign_keys=[user_id])


Index("ix_user_identities_user_id", UserIdentity.user_id)
Index("ix_refresh_tokens_user_id", RefreshToken.user_id)
Index("ix_refresh_tokens_expired_at", RefreshToken.expired_at)
