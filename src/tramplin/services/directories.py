from typing import Protocol

from tramplin.models.directories import Company, Interest, University


class CompanyRepositoryPort(Protocol):
    async def list_all(self) -> list[Company]: ...


class UniversityRepositoryPort(Protocol):
    async def list_all(self) -> list[University]: ...


class InterestRepositoryPort(Protocol):
    async def list_all(self) -> list[Interest]: ...


class CompanyService:
    def __init__(self, companies: CompanyRepositoryPort) -> None:
        self._companies = companies

    async def list_all(self) -> list[Company]:
        return await self._companies.list_all()


class UniversityService:
    def __init__(self, universities: UniversityRepositoryPort) -> None:
        self._universities = universities

    async def list_all(self) -> list[University]:
        return await self._universities.list_all()


class InterestService:
    def __init__(self, interests: InterestRepositoryPort) -> None:
        self._interests = interests

    async def list_all(self) -> list[Interest]:
        return await self._interests.list_all()
