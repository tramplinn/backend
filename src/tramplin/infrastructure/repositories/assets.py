import uuid_utils.compat as uuid

from tramplin.infrastructure.repositories.base import Repository
from tramplin.models.assets import Asset


class AssetRepository(Repository):
    async def get(self, asset_id: uuid.UUID) -> Asset | None:
        return await self._session.get(Asset, asset_id)

    def add(self, asset: Asset) -> Asset:
        self._session.add(asset)
        return asset
