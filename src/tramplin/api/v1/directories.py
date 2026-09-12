from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter

from tramplin.api.dependencies import CurrentUser
from tramplin.api.schemas.directories import CompanyOut, InterestOut, UniversityOut
from tramplin.services.directories import CompanyService, InterestService, UniversityService

router = APIRouter(tags=["directories"], route_class=DishkaRoute)


@router.get(
    "/companies",
    summary="Справочник компаний",
    description="Подсказки для поля «компания» в профиле; доступно любому вошедшему пользователю.",
)
async def list_companies(
    _: CurrentUser,
    service: FromDishka[CompanyService],
) -> list[CompanyOut]:
    return [CompanyOut(id=item.id, name=item.name) for item in await service.list_all()]


@router.get(
    "/universities",
    summary="Справочник вузов",
    description="Подсказки для поля «вуз» в профиле; доступно любому вошедшему пользователю.",
)
async def list_universities(
    _: CurrentUser,
    service: FromDishka[UniversityService],
) -> list[UniversityOut]:
    return [UniversityOut(id=item.id, name=item.name) for item in await service.list_all()]


@router.get(
    "/interests",
    summary="Справочник интересов",
    description="Подсказки для поля «интересы» в профиле; доступно любому вошедшему пользователю.",
)
async def list_interests(
    _: CurrentUser,
    service: FromDishka[InterestService],
) -> list[InterestOut]:
    return [InterestOut(id=item.id, name=item.name) for item in await service.list_all()]
