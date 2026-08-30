import enum
from datetime import datetime
from typing import Any

import uuid_utils.compat as uuid
from sqlalchemy import DateTime, Enum, ForeignKey, MetaData, event, func
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from tramplin.models.enums import (
    AssetMime,
    ContentStatus,
    IdentityProvider,
    QuestionType,
    UserRole,
)

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def new_id() -> uuid.UUID:
    """UUID v7: монотонен по времени, известен приложению до flush()."""
    return uuid.uuid7()


def pg_enum(enum_type: type[enum.Enum], name: str) -> Enum:
    """Нативный тип Postgres, хранящий значения членов, а не их имена."""
    return Enum(
        enum_type,
        name=name,
        values_callable=lambda members: [member.value for member in members],
    )


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    type_annotation_map = {  # noqa: RUF012  # SQLAlchemy требует обычный dict
        datetime: DateTime(timezone=True),
        uuid.UUID: postgresql.UUID(as_uuid=True),
        dict[str, Any]: postgresql.JSONB,
        list[Any]: postgresql.JSONB,
        AssetMime: pg_enum(AssetMime, "asset_mime"),
        ContentStatus: pg_enum(ContentStatus, "content_status"),
        IdentityProvider: pg_enum(IdentityProvider, "identity_provider"),
        QuestionType: pg_enum(QuestionType, "question_type"),
        UserRole: pg_enum(UserRole, "user_role"),
    }

    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), sort_order=100)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(),
        server_onupdate=func.now(),
        sort_order=101,
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL", use_alter=True),
        sort_order=102,
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL", use_alter=True),
        sort_order=103,
    )

    def __repr__(self) -> str:
        return f"<{type(self).__name__} id={getattr(self, 'id', None)}>"


class UUIDPrimaryKey:
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id, sort_order=-100)


@event.listens_for(Base, "init", propagate=True)
def _assign_uuid_pk(target: object, _args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
    """id нужен до flush(), чтобы связывать сущности в одной транзакции."""
    if isinstance(target, UUIDPrimaryKey) and kwargs.get("id") is None:
        kwargs["id"] = new_id()
