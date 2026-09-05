import enum
from datetime import UTC, datetime
from typing import Any

import uuid_utils.compat as uuid
from sqlalchemy import DateTime, Enum, ForeignKey, MetaData, event, func
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    ORMExecuteState,
    Session,
    mapped_column,
    with_loader_criteria,
)

from tramplin.models.enums import (
    AlgorithmDifficulty,
    AlgorithmProgressStatus,
    AlgorithmProvider,
    AlgorithmVerdict,
    AssetMime,
    ContentStatus,
    FeedbackStatus,
    IdentityProvider,
    PracticeMode,
    PracticeSessionStatus,
    QuestionType,
    RecommendationEntityType,
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
        FeedbackStatus: pg_enum(FeedbackStatus, "feedback_status"),
        IdentityProvider: pg_enum(IdentityProvider, "identity_provider"),
        QuestionType: pg_enum(QuestionType, "question_type"),
        PracticeMode: pg_enum(PracticeMode, "practice_mode"),
        PracticeSessionStatus: pg_enum(PracticeSessionStatus, "practice_session_status"),
        RecommendationEntityType: pg_enum(RecommendationEntityType, "recommendation_entity_type"),
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


class SoftDeleteMixin:
    """Помечает строку удалённой вместо DELETE. Строка остаётся в БД ради unique
    и на случай восстановления — фильтрация из выдачи идёт глобально, ниже."""

    __abstract__ = True

    is_deleted: Mapped[bool] = mapped_column(default=False, server_default="false", sort_order=104)
    deleted_at: Mapped[datetime | None] = mapped_column(default=None, sort_order=105)


def soft_delete(entity: SoftDeleteMixin) -> None:
    entity.is_deleted = True
    entity.deleted_at = datetime.now(UTC)


@event.listens_for(Session, "do_orm_execute")
def _exclude_soft_deleted(state: ORMExecuteState) -> None:
    """Единая точка фильтрации: без неё каждый репозиторий добавлял бы
    .where(is_deleted=False) вручную и рано или поздно кто-то забыл бы."""
    if state.is_select and not state.execution_options.get("include_deleted", False):
        state.statement = state.statement.options(
            with_loader_criteria(
                SoftDeleteMixin,
                lambda cls: cls.is_deleted.is_(False),
                include_aliases=True,
            )
        )
