from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter

from tramplin.api.dependencies import TeacherUser
from tramplin.api.schemas.tags import TagOut
from tramplin.api.tag_mapping import tags_out
from tramplin.services.tags import TagService

router = APIRouter(prefix="/tags", tags=["authoring:tags"], route_class=DishkaRoute)


@router.get("")
async def list_tags(_: TeacherUser, service: FromDishka[TagService]) -> list[TagOut]:
    return tags_out(await service.list_all())
