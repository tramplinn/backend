from sqlalchemy import Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from tramplin.models.base import UUIDPrimaryKey


class Company(UUIDPrimaryKey):
    """Справочник компаний для профиля пользователя: подсказки + свой вариант."""

    __tablename__ = "companies"
    __table_args__ = (Index("uq_companies_name_lower", text("lower(name)"), unique=True),)

    name: Mapped[str] = mapped_column(String(200))


class University(UUIDPrimaryKey):
    """Справочник вузов для профиля пользователя: подсказки + свой вариант."""

    __tablename__ = "universities"
    __table_args__ = (Index("uq_universities_name_lower", text("lower(name)"), unique=True),)

    name: Mapped[str] = mapped_column(String(200))


class Interest(UUIDPrimaryKey):
    """Справочник интересов для профиля пользователя.

    Отдельно от Tag: тот — курируемый словарь для курсов и задач, а интересы
    заполняют сами пользователи произвольным текстом и не должны в него попадать.
    """

    __tablename__ = "interests"
    __table_args__ = (Index("uq_interests_name_lower", text("lower(name)"), unique=True),)

    name: Mapped[str] = mapped_column(String(64))
