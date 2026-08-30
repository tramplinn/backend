import uuid_utils.compat as uuid
from sqlalchemy import func, select
from sqlalchemy.sql.elements import ColumnElement

from tramplin.infrastructure.repositories.base import Repository
from tramplin.models.assets import Asset
from tramplin.models.enums import AssetMime


class AssetRepository(Repository):
    async def list(
        self,
        *,
        query: str | None,
        mime: AssetMime | None,
        limit: int,
        offset: int,
    ) -> tuple[list[Asset], int]:
        filters: list[ColumnElement[bool]] = []
        if query:
            filters.append(Asset.filename.ilike(f"%{query}%"))
        if mime is not None:
            filters.append(Asset.mime == mime)

        count_stmt = select(func.count()).select_from(Asset).where(*filters)
        total = await self._session.scalar(count_stmt)
        stmt = (
            select(Asset)
            .where(*filters)
            .order_by(Asset.filename, Asset.id)
            .limit(limit)
            .offset(offset)
        )
        return list(await self._session.scalars(stmt)), total or 0

    async def get(self, asset_id: uuid.UUID) -> Asset | None:
        return await self._session.get(Asset, asset_id)

    def add(self, asset: Asset) -> Asset:
        self._session.add(asset)
        return asset

    async def delete(self, asset: Asset) -> None:
        await self._session.delete(asset)
