import logging
from dataclasses import dataclass
from pathlib import PurePath
from typing import Final, Protocol

import uuid_utils.compat as uuid

from tramplin.core.config import Settings
from tramplin.core.errors import InvalidUpdateError, NotFoundError, StorageError, UnprocessableError
from tramplin.models.assets import Asset
from tramplin.models.enums import AssetMime
from tramplin.services.contracts import Transaction


class AssetRepositoryPort(Protocol):
    async def get(self, asset_id: uuid.UUID) -> Asset | None: ...

    def add(self, asset: Asset) -> Asset: ...


async def resolve_image_asset(
    assets: AssetRepositoryPort,
    asset_id: uuid.UUID | None,
    *,
    owner: str,
) -> Asset | None:
    """Resolve an optional image reference shared by cover-bearing entities."""
    if asset_id is None:
        return None
    asset = await assets.get(asset_id)
    if asset is None:
        raise NotFoundError("Файл обложки не найден")
    if asset.mime is AssetMime.PDF:
        raise InvalidUpdateError(f"Обложкой {owner} может быть только изображение")
    return asset


class AssetStoragePort(Protocol):
    def public_url(self, key: str) -> str: ...

    async def upload(self, key: str, body: bytes, mime: AssetMime) -> str: ...

    async def delete(self, key: str) -> None: ...


EXTENSIONS: Final = {
    AssetMime.PNG: ".png",
    AssetMime.JPEG: ".jpg",
    AssetMime.WEBP: ".webp",
    AssetMime.GIF: ".gif",
    AssetMime.PDF: ".pdf",
}
logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class StoredAsset:
    asset: Asset
    url: str


class AssetService:
    def __init__(
        self,
        transaction: Transaction,
        assets: AssetRepositoryPort,
        storage: AssetStoragePort,
        settings: Settings,
    ) -> None:
        self._transaction = transaction
        self._assets = assets
        self._storage = storage
        self._max_bytes = settings.asset_max_bytes

    async def upload(
        self,
        filename: str,
        mime: AssetMime,
        body: bytes,
        actor_id: uuid.UUID,
    ) -> StoredAsset:
        clean_filename = PurePath(filename).name
        if not clean_filename or len(clean_filename) > 255:
            raise UnprocessableError("Некорректное имя файла")
        if not body:
            raise UnprocessableError("Файл пуст")
        if len(body) > self._max_bytes:
            raise UnprocessableError("Файл превышает допустимый размер", max_bytes=self._max_bytes)

        asset = Asset(
            filename=clean_filename,
            mime=mime,
            size=len(body),
            s3_key="pending",
            created_by=actor_id,
            updated_by=actor_id,
        )
        asset.s3_key = f"assets/{asset.id}{EXTENSIONS[mime]}"
        url = await self._storage.upload(asset.s3_key, body, mime)
        self._assets.add(asset)
        try:
            await self._transaction.commit()
        except Exception:
            try:
                await self._storage.delete(asset.s3_key)
            except StorageError:
                logger.exception("failed to compensate asset upload: %s", asset.s3_key)
            raise
        return StoredAsset(asset=asset, url=url)
