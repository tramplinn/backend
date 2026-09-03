import uuid_utils.compat as uuid
from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from tramplin.models.assets import Asset
from tramplin.models.base import Base, UUIDPrimaryKey
from tramplin.models.content import position_unique
from tramplin.models.enums import FeedbackStatus
from tramplin.models.users import User


class Feedback(UUIDPrimaryKey):
    """Сообщение из виджета обратной связи.

    author_id обнуляется вместе с пользователем, а не удаляет сообщение: разбирать
    жалобу нужно и после того, как её автор ушёл.
    """

    __tablename__ = "feedback"

    author_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
    )
    message: Mapped[str] = mapped_column(Text())
    # Откуда отправлено: без этого половина сообщений «тут ничего не работает».
    page_path: Mapped[str | None] = mapped_column(String(512))
    status: Mapped[FeedbackStatus] = mapped_column(default=FeedbackStatus.NEW)

    author: Mapped[User | None] = relationship(foreign_keys=[author_id])
    attachments: Mapped[list[FeedbackAttachment]] = relationship(
        back_populates="feedback",
        cascade="all, delete-orphan",
        order_by="FeedbackAttachment.position",
    )


class FeedbackAttachment(Base):
    __tablename__ = "feedback_attachments"
    __table_args__ = (position_unique("feedback_attachments", "feedback_id"),)

    feedback_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("feedback.id", ondelete="CASCADE"),
        primary_key=True,
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"),
        primary_key=True,
    )
    position: Mapped[int] = mapped_column(Integer(), default=0)

    feedback: Mapped[Feedback] = relationship(back_populates="attachments")
    asset: Mapped[Asset] = relationship()


Index("ix_feedback_status", Feedback.status)
