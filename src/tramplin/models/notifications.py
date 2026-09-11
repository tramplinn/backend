from datetime import datetime

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from tramplin.models.base import UUIDPrimaryKey
from tramplin.models.enums import EmailQueue


class EmailJobOutbox(UUIDPrimaryKey):
    """Транзакционный outbox: письмо целиком отрендерено здесь, email-service
    только доставляет — своих шаблонов и знания о домене у него нет."""

    __tablename__ = "email_job_outbox"

    to_email: Mapped[str] = mapped_column(String(320))
    subject: Mapped[str] = mapped_column(String(500))
    html_body: Mapped[str] = mapped_column(Text())
    text_body: Mapped[str] = mapped_column(Text())
    category: Mapped[str] = mapped_column(String(64))
    queue: Mapped[EmailQueue]
    dispatched_at: Mapped[datetime | None]
    attempts: Mapped[int] = mapped_column(Integer(), default=0)
    last_error: Mapped[str | None] = mapped_column(Text())
