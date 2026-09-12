from tramplin.api.v1.directories import list_companies, list_interests, list_universities
from tramplin.models.directories import Company, Interest, University
from tramplin.models.users import User
from tramplin.services.directories import CompanyService, InterestService, UniversityService


class FakeCompanies:
    def __init__(self, items: list[Company]) -> None:
        self.items = items

    async def list_all(self) -> list[Company]:
        return self.items


class FakeUniversities:
    def __init__(self, items: list[University]) -> None:
        self.items = items

    async def list_all(self) -> list[University]:
        return self.items


class FakeInterests:
    def __init__(self, items: list[Interest]) -> None:
        self.items = items

    async def list_all(self) -> list[Interest]:
        return self.items


async def test_company_service_lists_all() -> None:
    company = Company(name="Yandex")
    service = CompanyService(FakeCompanies([company]))

    assert await service.list_all() == [company]


async def test_university_service_lists_all() -> None:
    university = University(name="МГУ")
    service = UniversityService(FakeUniversities([university]))

    assert await service.list_all() == [university]


async def test_interest_service_lists_all() -> None:
    interest = Interest(name="Go")
    service = InterestService(FakeInterests([interest]))

    assert await service.list_all() == [interest]


async def test_directory_routes_return_dictionaries() -> None:
    company = Company(name="Yandex")
    university = University(name="МГУ")
    interest = Interest(name="Go")
    viewer = User(login="viewer")

    companies = await list_companies(viewer, CompanyService(FakeCompanies([company])))
    universities = await list_universities(
        viewer, UniversityService(FakeUniversities([university]))
    )
    interests = await list_interests(viewer, InterestService(FakeInterests([interest])))

    assert [item.name for item in companies] == ["Yandex"]
    assert [item.name for item in universities] == ["МГУ"]
    assert [item.name for item in interests] == ["Go"]
