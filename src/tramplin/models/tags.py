from sqlalchemy import Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from tramplin.models.base import UUIDPrimaryKey


class Tag(UUIDPrimaryKey):
    """Общий словарь тегов для курсов и алгоритмических задач."""

    __tablename__ = "tags"
    __table_args__ = (Index("uq_tags_name_lower", text("lower(name)"), unique=True),)

    name: Mapped[str] = mapped_column(String(64))
