from datetime import datetime
from typing import Final

import uuid_utils.compat as uuid
from sqlalchemy import Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from tramplin.models.base import UUIDPrimaryKey
from tramplin.models.enums import RecommendationEntityType

EMBEDDING_DIM: Final = 512


class EmbeddingJobOutbox(UUIDPrimaryKey):
    """Transactional outbox: одно событие пересчёта эмбеддинга на сущность."""

    __tablename__ = "embedding_job_outbox"
    __table_args__ = (UniqueConstraint("entity_type", "entity_id"),)

    entity_type: Mapped[RecommendationEntityType]
    entity_id: Mapped[uuid.UUID]
    dispatched_at: Mapped[datetime | None]
    attempts: Mapped[int] = mapped_column(Integer(), default=0)
    last_error: Mapped[str | None] = mapped_column(Text())
