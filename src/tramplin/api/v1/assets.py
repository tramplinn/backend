from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, File, Form, UploadFile, status

from tramplin.api.dependencies import CurrentUser
from tramplin.api.schemas.assets import AssetOut
from tramplin.models.enums import AssetMime
from tramplin.services.assets import AssetService, StoredAsset

router = APIRouter(prefix="/assets", tags=["assets"], route_class=DishkaRoute)


def _asset_out(stored: StoredAsset) -> AssetOut:
    return AssetOut(
        id=stored.asset.id,
        filename=stored.asset.filename,
        mime=stored.asset.mime,
        size=stored.asset.size,
        url=stored.url,
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def upload_asset(
    file: Annotated[UploadFile, File()],
    mime: Annotated[AssetMime, Form()],
    user: CurrentUser,
    assets: FromDishka[AssetService],
) -> AssetOut:
    body = await file.read()
    return _asset_out(await assets.upload(file.filename or "", mime, body, user.id))
