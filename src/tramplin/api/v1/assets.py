from typing import Annotated

import uuid_utils.compat as uuid
from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Body, Query, status

from tramplin.api.dependencies import CurrentUser, TeacherUser
from tramplin.api.schemas.assets import AssetOut
from tramplin.api.schemas.pagination import PageOut
from tramplin.models.enums import AssetMime
from tramplin.services.assets import AssetService, StoredAsset

router = APIRouter(prefix="/assets", tags=["assets"], route_class=DishkaRoute)

Filename = Annotated[str, Query(min_length=1, max_length=255)]
FileBody = Annotated[bytes, Body(media_type="application/octet-stream")]


def _asset_out(stored: StoredAsset) -> AssetOut:
    return AssetOut(
        id=stored.asset.id,
        filename=stored.asset.filename,
        mime=stored.asset.mime,
        size=stored.asset.size,
        url=stored.url,
    )


@router.get("")
async def list_assets(
    _: TeacherUser,
    assets: FromDishka[AssetService],
    q: str | None = Query(default=None, max_length=255),
    mime: AssetMime | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> PageOut[AssetOut]:
    page = await assets.list_assets(query=q, mime=mime, limit=limit, offset=offset)
    return PageOut(
        items=[_asset_out(asset) for asset in page.items],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def upload_asset(
    filename: Filename,
    mime: AssetMime,
    body: FileBody,
    user: CurrentUser,
    assets: FromDishka[AssetService],
) -> AssetOut:
    return _asset_out(await assets.upload(filename, mime, body, user.id))


@router.delete("/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_asset(
    asset_id: uuid.UUID,
    _: TeacherUser,
    assets: FromDishka[AssetService],
) -> None:
    await assets.delete(asset_id)
