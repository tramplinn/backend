from typing import Annotated

import uuid_utils.compat as uuid
from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query, status

from tramplin.api.dependencies import CurrentUser, OptionalUser
from tramplin.api.project_mapping import (
    invite_out,
    members_out,
    project_card_out,
    project_out,
    status_event_out,
)
from tramplin.api.schemas.pagination import PageOut
from tramplin.api.schemas.projects import (
    ProfileLayoutIn,
    ProfileLayoutItemSchema,
    ProfileLayoutOut,
    ProfileProjectsOrderIn,
    ProjectCardOut,
    ProjectCreate,
    ProjectInviteCreate,
    ProjectInviteOut,
    ProjectLinksIn,
    ProjectMemberOut,
    ProjectMemberUpdate,
    ProjectOut,
    ProjectStatusEventOut,
    ProjectStatusIn,
    ProjectTransferIn,
    ProjectUpdate,
)
from tramplin.core.config import Settings
from tramplin.models.enums import ProjectLinkKind, ProjectStatus
from tramplin.services.profile_layout import ProfileLayoutItem, ProfileLayoutService
from tramplin.services.projects import (
    ProfileProjectOrder,
    ProjectCatalogFilters,
    ProjectLinkInput,
    ProjectService,
    ProjectSort,
)

router = APIRouter(prefix="/projects", tags=["projects"], route_class=DishkaRoute)
me_router = APIRouter(prefix="/me", tags=["projects"], route_class=DishkaRoute)

SearchQuery = Annotated[str | None, Query(max_length=200)]
StatusFilter = Annotated[list[ProjectStatus] | None, Query(alias="status")]
LinkKindFilter = Annotated[list[ProjectLinkKind] | None, Query()]
MemberFilter = Annotated[str | None, Query(max_length=64)]


@router.get(
    "",
    summary="Каталог проектов",
    description=(
        "Публичные проекты (и для вошедших — проекты для авторизованных) с поиском и "
        "фильтрами; private-проекты сюда не попадают, их отдаёт /me/projects."
    ),
)
async def list_projects(
    viewer: OptionalUser,
    projects: FromDishka[ProjectService],
    settings: FromDishka[Settings],
    q: SearchQuery = None,
    statuses: StatusFilter = None,
    link_kind: LinkKindFilter = None,
    member: MemberFilter = None,
    sort: ProjectSort = "updated",
    limit: int = Query(default=24, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
) -> PageOut[ProjectCardOut]:
    filters = ProjectCatalogFilters(
        query=q.strip() if q else None,
        statuses=statuses or (),
        link_kinds=link_kind or (),
        member_login=member,
        sort=sort,
    )
    page = await projects.catalog(viewer, filters, limit=limit, offset=offset)
    base_url = settings.s3_public_base_url
    return PageOut(
        items=[project_card_out(item, asset_base_url=base_url) for item in page.items],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Создать проект",
    description="Автор становится владельцем; slug строится из названия транслитерацией.",
)
async def create_project(
    payload: ProjectCreate,
    user: CurrentUser,
    projects: FromDishka[ProjectService],
    settings: FromDishka[Settings],
) -> ProjectOut:
    view = await projects.create(
        user, title=payload.title, summary=payload.summary, visibility=payload.visibility
    )
    return project_out(view, asset_base_url=settings.s3_public_base_url)


@router.get(
    "/{slug}",
    summary="Проект",
    description="Полная карточка проекта с ролью текущего пользователя; скрытый проект — 404.",
)
async def get_project(
    slug: str,
    viewer: OptionalUser,
    projects: FromDishka[ProjectService],
    settings: FromDishka[Settings],
) -> ProjectOut:
    view = await projects.get(slug, viewer)
    return project_out(view, asset_base_url=settings.s3_public_base_url)


@router.patch(
    "/{slug}",
    summary="Изменить проект",
    description=(
        "README, описание и логотип — contributor+; название, slug и видимость — maintainer+."
    ),
)
async def update_project(
    slug: str,
    payload: ProjectUpdate,
    user: CurrentUser,
    projects: FromDishka[ProjectService],
    settings: FromDishka[Settings],
) -> ProjectOut:
    view = await projects.update(slug, user, payload.model_dump(exclude_unset=True))
    return project_out(view, asset_base_url=settings.s3_public_base_url)


@router.delete(
    "/{slug}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить проект",
    description="Только владелец; удаляет участников, ссылки и историю каскадом.",
)
async def delete_project(
    slug: str,
    user: CurrentUser,
    projects: FromDishka[ProjectService],
) -> None:
    await projects.delete(slug, user)


@router.post(
    "/{slug}/status",
    summary="Сменить статус проекта",
    description="maintainer+; каждая смена пишется в историю.",
)
async def change_project_status(
    slug: str,
    payload: ProjectStatusIn,
    user: CurrentUser,
    projects: FromDishka[ProjectService],
    settings: FromDishka[Settings],
) -> ProjectOut:
    view = await projects.change_status(slug, user, payload.status)
    return project_out(view, asset_base_url=settings.s3_public_base_url)


@router.get(
    "/{slug}/status-events",
    summary="История статусов проекта",
    description="Новые события первыми; доступ — как к самому проекту.",
)
async def list_status_events(
    slug: str,
    viewer: OptionalUser,
    projects: FromDishka[ProjectService],
) -> list[ProjectStatusEventOut]:
    return [status_event_out(event) for event in await projects.status_events(slug, viewer)]


@router.put(
    "/{slug}/links",
    summary="Заменить ссылки проекта",
    description="contributor+; список заменяется целиком, порядок — порядок массива.",
)
async def replace_links(
    slug: str,
    payload: ProjectLinksIn,
    user: CurrentUser,
    projects: FromDishka[ProjectService],
    settings: FromDishka[Settings],
) -> ProjectOut:
    links = [
        ProjectLinkInput(kind=item.kind, url=item.url, label=item.label) for item in payload.links
    ]
    view = await projects.replace_links(slug, user, links)
    return project_out(view, asset_base_url=settings.s3_public_base_url)


@router.get(
    "/{slug}/members",
    summary="Участники проекта",
    description="Публичные поля участников с ролями и подписями.",
)
async def list_members(
    slug: str,
    viewer: OptionalUser,
    projects: FromDishka[ProjectService],
) -> list[ProjectMemberOut]:
    return members_out(await projects.members(slug, viewer))


@router.patch(
    "/{slug}/members/{login}",
    summary="Изменить участника",
    description="Роль меняет владелец; подпись — maintainer+ или сам участник.",
)
async def update_member(
    slug: str,
    login: str,
    payload: ProjectMemberUpdate,
    user: CurrentUser,
    projects: FromDishka[ProjectService],
) -> list[ProjectMemberOut]:
    await projects.update_member(slug, user, login, payload.model_dump(exclude_unset=True))
    return members_out(await projects.members(slug, user))


@router.delete(
    "/{slug}/members/{login}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Исключить участника или выйти",
    description="Свой логин — выход из проекта; чужой — исключение участника ниже своей роли.",
)
async def remove_member(
    slug: str,
    login: str,
    user: CurrentUser,
    projects: FromDishka[ProjectService],
) -> None:
    await projects.remove_member(slug, user, login)


@router.post(
    "/{slug}/transfer",
    summary="Передать владение",
    description="Новый владелец — существующий участник; прежний становится maintainer.",
)
async def transfer_ownership(
    slug: str,
    payload: ProjectTransferIn,
    user: CurrentUser,
    projects: FromDishka[ProjectService],
    settings: FromDishka[Settings],
) -> ProjectOut:
    view = await projects.transfer(slug, user, payload.login)
    return project_out(view, asset_base_url=settings.s3_public_base_url)


@router.get(
    "/{slug}/invites",
    summary="Активные приглашения проекта",
    description="maintainer+; просроченные закрываются при чтении.",
)
async def list_project_invites(
    slug: str,
    user: CurrentUser,
    projects: FromDishka[ProjectService],
    settings: FromDishka[Settings],
) -> list[ProjectInviteOut]:
    invites = await projects.project_invites(slug, user)
    return [invite_out(item, asset_base_url=settings.s3_public_base_url) for item in invites]


@router.post(
    "/{slug}/invites",
    status_code=status.HTTP_201_CREATED,
    summary="Пригласить в проект",
    description="maintainer+, на роль ниже своей; письмо уходит, если у пользователя есть почта.",
)
async def create_invite(
    slug: str,
    payload: ProjectInviteCreate,
    user: CurrentUser,
    projects: FromDishka[ProjectService],
    settings: FromDishka[Settings],
) -> ProjectInviteOut:
    invite = await projects.invite(
        slug, user, login=payload.login, role=payload.role, title=payload.title
    )
    return invite_out(invite, asset_base_url=settings.s3_public_base_url)


@router.delete(
    "/{slug}/invites/{invite_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Отозвать приглашение",
    description="maintainer+; приглашение переходит в revoked.",
)
async def revoke_invite(
    slug: str,
    invite_id: uuid.UUID,
    user: CurrentUser,
    projects: FromDishka[ProjectService],
) -> None:
    await projects.revoke_invite(slug, user, invite_id)


@me_router.get(
    "/projects",
    summary="Мои проекты",
    description="Все проекты с моим участием в любой роли, включая private, в порядке профиля.",
)
async def my_projects(
    user: CurrentUser,
    projects: FromDishka[ProjectService],
    settings: FromDishka[Settings],
) -> list[ProjectCardOut]:
    views = await projects.list_mine(user)
    return [project_card_out(item, asset_base_url=settings.s3_public_base_url) for item in views]


@me_router.put(
    "/projects/order",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Порядок проектов в профиле",
    description="Полный список моих проектов: порядок и признак показа в профиле.",
)
async def reorder_my_projects(
    payload: ProfileProjectsOrderIn,
    user: CurrentUser,
    projects: FromDishka[ProjectService],
) -> None:
    await projects.reorder_profile(
        user,
        [
            ProfileProjectOrder(project_id=item.project_id, show_in_profile=item.show_in_profile)
            for item in payload.items
        ],
    )


@me_router.get(
    "/invites",
    summary="Входящие приглашения",
    description="Ожидающие ответа приглашения в проекты.",
)
async def my_invites(
    user: CurrentUser,
    projects: FromDishka[ProjectService],
    settings: FromDishka[Settings],
) -> list[ProjectInviteOut]:
    invites = await projects.my_invites(user)
    return [invite_out(item, asset_base_url=settings.s3_public_base_url) for item in invites]


@me_router.post(
    "/invites/{invite_id}/accept",
    summary="Принять приглашение",
    description="Добавляет в участники проекта с ролью из приглашения.",
)
async def accept_invite(
    invite_id: uuid.UUID,
    user: CurrentUser,
    projects: FromDishka[ProjectService],
    settings: FromDishka[Settings],
) -> ProjectCardOut:
    view = await projects.accept_invite(user, invite_id)
    return project_card_out(view, asset_base_url=settings.s3_public_base_url)


@me_router.post(
    "/invites/{invite_id}/decline",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Отклонить приглашение",
    description="Приглашение переходит в declined; пригласить снова можно.",
)
async def decline_invite(
    invite_id: uuid.UUID,
    user: CurrentUser,
    projects: FromDishka[ProjectService],
) -> None:
    await projects.decline_invite(user, invite_id)


@me_router.get(
    "/profile-layout",
    summary="Раскладка публичного профиля",
    description="Все блоки профиля в сохранённом порядке с флагами видимости.",
)
async def get_profile_layout(
    user: CurrentUser,
    layout: FromDishka[ProfileLayoutService],
) -> ProfileLayoutOut:
    return _layout_out(await layout.get(user.id))


@me_router.put(
    "/profile-layout",
    summary="Сохранить раскладку профиля",
    description="Каждый блок ровно один раз; порядок — порядок массива.",
)
async def save_profile_layout(
    payload: ProfileLayoutIn,
    user: CurrentUser,
    layout: FromDishka[ProfileLayoutService],
) -> ProfileLayoutOut:
    items = [ProfileLayoutItem(block=item.block, visible=item.visible) for item in payload.blocks]
    return _layout_out(await layout.save(user.id, items))


def _layout_out(items: list[ProfileLayoutItem]) -> ProfileLayoutOut:
    return ProfileLayoutOut(
        blocks=[ProfileLayoutItemSchema(block=item.block, visible=item.visible) for item in items]
    )
