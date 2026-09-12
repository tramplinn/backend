from collections.abc import Sequence

from sqlalchemy import func, select

from tramplin.infrastructure.repositories.base import Repository
from tramplin.models.directories import Company, Interest, University


class CompanyRepository(Repository):
    async def list_all(self) -> list[Company]:
        stmt = select(Company).order_by(Company.name)
        return list(await self._session.scalars(stmt))

    async def get_or_create_one(self, name: str) -> Company:
        clean = name.strip()
        existing = await self._get_by_lower_name(clean.lower())
        if existing is not None:
            return existing
        return self.add(Company(name=clean))

    async def _get_by_lower_name(self, lower_name: str) -> Company | None:
        stmt = select(Company).where(func.lower(Company.name) == lower_name)
        return (await self._session.scalars(stmt)).one_or_none()


class UniversityRepository(Repository):
    async def list_all(self) -> list[University]:
        stmt = select(University).order_by(University.name)
        return list(await self._session.scalars(stmt))

    async def get_or_create_one(self, name: str) -> University:
        clean = name.strip()
        existing = await self._get_by_lower_name(clean.lower())
        if existing is not None:
            return existing
        return self.add(University(name=clean))

    async def _get_by_lower_name(self, lower_name: str) -> University | None:
        stmt = select(University).where(func.lower(University.name) == lower_name)
        return (await self._session.scalars(stmt)).one_or_none()


class InterestRepository(Repository):
    async def list_all(self) -> list[Interest]:
        stmt = select(Interest).order_by(Interest.name)
        return list(await self._session.scalars(stmt))

    async def get_or_create_many(self, names: Sequence[str]) -> list[Interest]:
        """Сохраняет порядок первого появления, дедуп и поиск существующих — без учёта регистра."""
        resolved: list[Interest] = []
        seen: set[str] = set()
        for raw in names:
            name = raw.strip()
            if not name:
                continue
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            interest = await self._get_by_lower_name(key)
            if interest is None:
                interest = Interest(name=name)
                self.add(interest)
            resolved.append(interest)
        return resolved

    async def _get_by_lower_name(self, lower_name: str) -> Interest | None:
        stmt = select(Interest).where(func.lower(Interest.name) == lower_name)
        return (await self._session.scalars(stmt)).one_or_none()
