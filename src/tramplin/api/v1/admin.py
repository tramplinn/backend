import uuid_utils.compat as uuid
from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query, status

from tramplin.api.dependencies import AdminUser
from tramplin.api.schemas.pagination import PageOut
from tramplin.api.schemas.users import (
    StudentGroupCreate,
    StudentGroupOut,
    StudentGroupUpdate,
    UserAdminUpdate,
    UserOut,
)
from tramplin.models.enums import UserRole
from tramplin.models.users import StudentGroup
from tramplin.services.groups import GroupService
from tramplin.services.users import UserService

router = APIRouter(prefix="/admin", tags=["admin"], route_class=DishkaRoute)


@router.get("/users")
async def list_users(
    _: AdminUser,
    users: FromDishka[UserService],
    q: str | None = Query(default=None, max_length=200),
    role: UserRole | None = None,
    group_id: uuid.UUID | None = None,
    is_active: bool | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> PageOut[UserOut]:
    page = await users.list(
        query=q,
        role=role,
        group_id=group_id,
        is_active=is_active,
        limit=limit,
        offset=offset,
    )
    return PageOut(
        items=[UserOut.model_validate(user) for user in page.items],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


@router.patch("/users/{user_id}")
async def update_user(
    user_id: uuid.UUID,
    payload: UserAdminUpdate,
    admin: AdminUser,
    users: FromDishka[UserService],
) -> UserOut:
    user = await users.update(admin.id, user_id, payload.model_dump(exclude_unset=True))
    return UserOut.model_validate(user)


@router.get("/groups")
async def list_groups(_: AdminUser, groups: FromDishka[GroupService]) -> list[StudentGroupOut]:
    return [StudentGroupOut.model_validate(group) for group in await groups.list()]


@router.post("/groups", status_code=status.HTTP_201_CREATED)
async def create_group(
    payload: StudentGroupCreate,
    user: AdminUser,
    groups: FromDishka[GroupService],
) -> StudentGroupOut:
    group = await groups.create(StudentGroup(**payload.model_dump()), user.id)
    return StudentGroupOut.model_validate(group)


@router.patch("/groups/{group_id}")
async def update_group(
    group_id: uuid.UUID,
    payload: StudentGroupUpdate,
    user: AdminUser,
    groups: FromDishka[GroupService],
) -> StudentGroupOut:
    group = await groups.update(
        group_id,
        payload.model_dump(exclude_unset=True),
        user.id,
    )
    return StudentGroupOut.model_validate(group)


@router.delete("/groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group(
    group_id: uuid.UUID,
    _: AdminUser,
    groups: FromDishka[GroupService],
) -> None:
    await groups.delete(group_id)
