import uuid_utils.compat as uuid
from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, status

from tramplin.api.content_mapping import module_tree_out
from tramplin.api.dependencies import TeacherUser
from tramplin.api.schemas.modules import (
    ItemsOrder,
    ModuleContentOrder,
    ModuleCreate,
    ModuleDependencyCreate,
    ModuleDependencyOut,
    ModuleOut,
    ModuleTreeOut,
    ModuleUpdate,
)
from tramplin.core.config import Settings
from tramplin.models.content import Module
from tramplin.services.modules import ModuleService

router = APIRouter(route_class=DishkaRoute)


@router.get("/courses/{slug}/module-dependencies")
async def list_module_dependencies(
    slug: str,
    _: TeacherUser,
    modules: FromDishka[ModuleService],
) -> list[ModuleDependencyOut]:
    return [
        ModuleDependencyOut.model_validate(dependency)
        for dependency in await modules.list_dependencies(slug, published_only=False)
    ]


@router.post("/courses/{course_id}/modules", status_code=status.HTTP_201_CREATED)
async def create_module(
    course_id: uuid.UUID,
    payload: ModuleCreate,
    user: TeacherUser,
    modules: FromDishka[ModuleService],
) -> ModuleOut:
    module = Module(course_id=course_id, **payload.model_dump())
    return ModuleOut.model_validate(await modules.create(course_id, module, user.id))


@router.get("/modules/{module_id}")
async def get_module(
    module_id: uuid.UUID,
    _: TeacherUser,
    modules: FromDishka[ModuleService],
    settings: FromDishka[Settings],
) -> ModuleTreeOut:
    """Черновики видны: публичного роута для одного модуля нет вовсе."""
    return module_tree_out(
        await modules.get_tree(module_id),
        published_only=False,
        asset_base_url=settings.s3_public_base_url,
    )


@router.patch("/modules/{module_id}")
async def update_module(
    module_id: uuid.UUID,
    payload: ModuleUpdate,
    user: TeacherUser,
    modules: FromDishka[ModuleService],
) -> ModuleOut:
    module = await modules.update(module_id, payload.model_dump(exclude_unset=True), user.id)
    return ModuleOut.model_validate(module)


@router.put("/modules/{module_id}/dependencies", status_code=status.HTTP_204_NO_CONTENT)
async def add_module_dependency(
    module_id: uuid.UUID,
    payload: ModuleDependencyCreate,
    user: TeacherUser,
    modules: FromDishka[ModuleService],
) -> None:
    await modules.add_dependency(module_id, payload.depends_on_id, user.id)


@router.delete(
    "/modules/{module_id}/dependencies/{depends_on_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_module_dependency(
    module_id: uuid.UUID,
    depends_on_id: uuid.UUID,
    _: TeacherUser,
    modules: FromDishka[ModuleService],
) -> None:
    await modules.remove_dependency(module_id, depends_on_id)


@router.put("/courses/{course_id}/modules/order", status_code=status.HTTP_204_NO_CONTENT)
async def reorder_modules(
    course_id: uuid.UUID,
    payload: ItemsOrder,
    user: TeacherUser,
    modules: FromDishka[ModuleService],
) -> None:
    await modules.reorder(course_id, payload.ids, user.id)


@router.put("/modules/{module_id}/order", status_code=status.HTTP_204_NO_CONTENT)
async def reorder_module_content(
    module_id: uuid.UUID,
    payload: ModuleContentOrder,
    user: TeacherUser,
    modules: FromDishka[ModuleService],
) -> None:
    await modules.reorder_content(
        module_id,
        payload.ids,
        user.id,
    )


@router.delete("/modules/{module_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_module(
    module_id: uuid.UUID,
    _: TeacherUser,
    modules: FromDishka[ModuleService],
) -> None:
    await modules.delete(module_id)
