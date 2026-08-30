import pytest

from tramplin.core.config import Settings
from tramplin.core.errors import StorageError, UnprocessableError
from tramplin.models.assets import Asset
from tramplin.models.enums import AssetMime
from tramplin.services.assets import AssetService


class AssetTransaction:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    async def commit(self) -> None:
        if self.fail:
            raise RuntimeError("database unavailable")


class AssetRepositoryFake:
    def __init__(self) -> None:
        self.assets: list[Asset] = []

    async def list(
        self,
        *,
        query: str | None,
        mime: AssetMime | None,
        limit: int,
        offset: int,
    ) -> tuple[list[Asset], int]:
        assets = self.assets
        if query:
            assets = [asset for asset in assets if query.casefold() in asset.filename.casefold()]
        if mime is not None:
            assets = [asset for asset in assets if asset.mime == mime]
        return assets[offset : offset + limit], len(assets)

    async def get(self, asset_id: object) -> Asset | None:
        return next((asset for asset in self.assets if asset.id == asset_id), None)

    def add(self, asset: Asset) -> Asset:
        self.assets.append(asset)
        return asset

    async def delete(self, asset: Asset) -> None:
        self.assets.remove(asset)


class AssetStorageFake:
    def __init__(self) -> None:
        self.uploaded: list[str] = []
        self.deleted: list[str] = []

    def public_url(self, key: str) -> str:
        return f"https://assets.test/{key}"

    async def upload(self, key: str, body: bytes, mime: AssetMime) -> str:
        self.uploaded.append(key)
        return self.public_url(key)

    async def delete(self, key: str) -> None:
        self.deleted.append(key)


async def test_upload_generates_server_key_and_audit_fields(settings: Settings) -> None:
    repository = AssetRepositoryFake()
    storage = AssetStorageFake()
    service = AssetService(AssetTransaction(), repository, storage, settings)
    actor_id = Asset(filename="actor", s3_key="actor", mime=AssetMime.PNG, size=1).id

    result = await service.upload("../lesson.png", AssetMime.PNG, b"image", actor_id)

    assert result.asset.filename == "lesson.png"
    assert result.asset.s3_key == f"assets/{result.asset.id}.png"
    assert result.asset.created_by == actor_id
    assert storage.uploaded == [result.asset.s3_key]


async def test_upload_compensates_storage_when_commit_fails(settings: Settings) -> None:
    repository = AssetRepositoryFake()
    storage = AssetStorageFake()
    service = AssetService(AssetTransaction(fail=True), repository, storage, settings)
    actor_id = Asset(filename="actor", s3_key="actor", mime=AssetMime.PNG, size=1).id

    with pytest.raises(RuntimeError, match="database unavailable"):
        await service.upload("lesson.pdf", AssetMime.PDF, b"document", actor_id)

    assert storage.deleted == storage.uploaded


async def test_upload_rejects_oversized_file(settings: Settings) -> None:
    settings.asset_max_bytes = 2
    storage = AssetStorageFake()
    service = AssetService(AssetTransaction(), AssetRepositoryFake(), storage, settings)
    actor_id = Asset(filename="actor", s3_key="actor", mime=AssetMime.PNG, size=1).id

    with pytest.raises(UnprocessableError):
        await service.upload("large.png", AssetMime.PNG, b"123", actor_id)

    assert storage.uploaded == []


async def test_asset_list_filters_and_returns_page(settings: Settings) -> None:
    repository = AssetRepositoryFake()
    repository.assets.extend(
        [
            Asset(filename="lesson.png", s3_key="assets/1.png", mime=AssetMime.PNG, size=1),
            Asset(filename="lesson.pdf", s3_key="assets/2.pdf", mime=AssetMime.PDF, size=1),
        ]
    )
    service = AssetService(AssetTransaction(), repository, AssetStorageFake(), settings)

    page = await service.list_assets(query="lesson", mime=AssetMime.PDF, limit=10)

    assert [item.asset.filename for item in page.items] == ["lesson.pdf"]
    assert page.total == 1


async def test_delete_commits_metadata_before_removing_object(settings: Settings) -> None:
    events: list[str] = []

    class OrderedTransaction(AssetTransaction):
        async def commit(self) -> None:
            events.append("commit")

    class OrderedStorage(AssetStorageFake):
        async def delete(self, key: str) -> None:
            events.append("storage")
            await super().delete(key)

    repository = AssetRepositoryFake()
    asset = repository.add(
        Asset(filename="lesson.png", s3_key="assets/lesson.png", mime=AssetMime.PNG, size=1)
    )
    service = AssetService(OrderedTransaction(), repository, OrderedStorage(), settings)

    await service.delete(asset.id)

    assert events == ["commit", "storage"]
    assert repository.assets == []


async def test_delete_tolerates_orphan_when_storage_is_down(settings: Settings) -> None:
    class FailingStorage(AssetStorageFake):
        async def delete(self, key: str) -> None:
            raise StorageError

    repository = AssetRepositoryFake()
    asset = repository.add(
        Asset(filename="lesson.png", s3_key="assets/lesson.png", mime=AssetMime.PNG, size=1)
    )
    service = AssetService(AssetTransaction(), repository, FailingStorage(), settings)

    await service.delete(asset.id)

    assert repository.assets == []
