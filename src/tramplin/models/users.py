from datetime import datetime

import uuid_utils.compat as uuid
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from tramplin.models.assets import Asset
from tramplin.models.base import Base, UUIDPrimaryKey
from tramplin.models.directories import Company, Interest, University
from tramplin.models.enums import IdentityProvider, UserRole

user_interests = Table(
    "user_interests",
    Base.metadata,
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("interest_id", ForeignKey("interests.id", ondelete="CASCADE"), primary_key=True),
)


class User(UUIDPrimaryKey):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "experience_years >= 0 AND experience_years <= 80",
            name="experience_years_range",
        ),
    )

    login: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str | None] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(320), unique=True)
    avatar_url: Mapped[str | None] = mapped_column(String(512))
    student_number: Mapped[str | None] = mapped_column(String(32), unique=True)
    headline: Mapped[str | None] = mapped_column(String(120))
    bio: Mapped[str | None] = mapped_column(Text())
    specialty: Mapped[str | None] = mapped_column(String(32))
    grade: Mapped[str | None] = mapped_column(String(16))
    experience_years: Mapped[int | None] = mapped_column(SmallInteger())
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL")
    )
    university_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("universities.id", ondelete="SET NULL")
    )
    resume_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL")
    )
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
    company: Mapped[Company | None] = relationship(foreign_keys=[company_id])
    university: Mapped[University | None] = relationship(foreign_keys=[university_id])
    resume_asset: Mapped[Asset | None] = relationship(foreign_keys=[resume_asset_id])
    interests: Mapped[list[Interest]] = relationship(
        secondary=user_interests, order_by="Interest.name"
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
Index("ix_users_company_id", User.company_id)
Index("ix_users_university_id", User.university_id)
Index("ix_users_resume_asset_id", User.resume_asset_id)
