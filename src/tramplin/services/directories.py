from typing import Protocol

from tramplin.models.directories import Company, Interest, University


class DirectoryRepositoryPort[T](Protocol):
    async def list_all(self) -> list[T]: ...


class DirectoryService[T]:
    def __init__(self, directory: DirectoryRepositoryPort[T]) -> None:
        self._directory = directory

    async def list_all(self) -> list[T]:
        return await self._directory.list_all()


class CompanyRepositoryPort(DirectoryRepositoryPort[Company], Protocol): ...


class UniversityRepositoryPort(DirectoryRepositoryPort[University], Protocol): ...


class InterestRepositoryPort(DirectoryRepositoryPort[Interest], Protocol): ...


class CompanyService(DirectoryService[Company]): ...


class UniversityService(DirectoryService[University]): ...


class InterestService(DirectoryService[Interest]): ...
