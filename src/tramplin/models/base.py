import enum
from datetime import datetime
from typing import Any

import uuid_utils.compat as uuid
from sqlalchemy import DateTime, Enum, ForeignKey, MetaData, func
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from tramplin.models.enums import (
    AlgorithmDifficulty,
    AlgorithmProgressStatus,
    AlgorithmProvider,
    AlgorithmVerdict,
    AssetMime,
    ContentStatus,
    IdentityProvider,
    PracticeMode,
    PracticeSessionStatus,
    QuestionType,
    SubmissionKind,
    SubmissionStatus,
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
        AlgorithmDifficulty: pg_enum(AlgorithmDifficulty, "algorithm_difficulty"),
        AlgorithmProgressStatus: pg_enum(AlgorithmProgressStatus, "algorithm_progress_status"),
        AlgorithmProvider: pg_enum(AlgorithmProvider, "algorithm_provider"),
        AlgorithmVerdict: pg_enum(AlgorithmVerdict, "algorithm_verdict"),
        ContentStatus: pg_enum(ContentStatus, "content_status"),
        IdentityProvider: pg_enum(IdentityProvider, "identity_provider"),
        QuestionType: pg_enum(QuestionType, "question_type"),
        PracticeMode: pg_enum(PracticeMode, "practice_mode"),
        PracticeSessionStatus: pg_enum(PracticeSessionStatus, "practice_session_status"),
        SubmissionKind: pg_enum(SubmissionKind, "submission_kind"),
        SubmissionStatus: pg_enum(SubmissionStatus, "submission_status"),
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
        return f"<{type(self).__name__}>"


class UUIDPrimaryKey(Base):
    __abstract__ = True

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id, sort_order=-100)

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("id", new_id())
        super().__init__(**kwargs)

    def __repr__(self) -> str:
        return f"<{type(self).__name__} id={self.id}>"
