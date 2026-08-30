from sqlalchemy import BigInteger, CheckConstraint, String
from sqlalchemy.orm import Mapped, mapped_column

from tramplin.models.base import Base, UUIDPrimaryKey
from tramplin.models.enums import AssetMime


class Asset(UUIDPrimaryKey, Base):
    __tablename__ = "assets"
    __table_args__ = (CheckConstraint("size > 0", name="size_positive"),)

    s3_key: Mapped[str] = mapped_column(String(512), unique=True)
    filename: Mapped[str] = mapped_column(String(255))
    mime: Mapped[AssetMime]
    size: Mapped[int] = mapped_column(BigInteger())
