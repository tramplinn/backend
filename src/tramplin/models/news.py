from datetime import datetime

import uuid_utils.compat as uuid
from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from tramplin.models.assets import Asset
from tramplin.models.base import Base, UUIDPrimaryKey
from tramplin.models.content import position_unique, status_column
from tramplin.models.enums import ContentStatus


class News(UUIDPrimaryKey):
    """Новость главной страницы. Лента строится по published_at, а не по created_at:
    порядок публикации задаёт редактор, а не момент, когда он завёл черновик."""

    __tablename__ = "news"
    __table_args__ = (UniqueConstraint("slug", name="uq_news_slug"),)

    title: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(120))
    summary: Mapped[str | None] = mapped_column(Text())
    body_md: Mapped[str] = mapped_column(Text(), default="")
    status: Mapped[ContentStatus] = status_column()
    published_at: Mapped[datetime | None] = mapped_column()

    photos: Mapped[list[NewsPhoto]] = relationship(
        back_populates="news",
        cascade="all, delete-orphan",
        order_by="NewsPhoto.position",
    )


class NewsPhoto(Base):
    """Связка новости с загруженным файлом. Позиция здесь, а не в assets:
    один и тот же файл может стоять в разных новостях на разных местах."""

    __tablename__ = "news_photos"
    __table_args__ = (position_unique("news_photos", "news_id"),)

    news_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("news.id", ondelete="CASCADE"),
        primary_key=True,
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"),
        primary_key=True,
    )
    position: Mapped[int] = mapped_column(Integer(), default=0)

    news: Mapped[News] = relationship(back_populates="photos")
    asset: Mapped[Asset] = relationship()


Index("ix_news_published_at", News.published_at.desc())
