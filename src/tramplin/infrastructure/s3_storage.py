import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING

from botocore.exceptions import BotoCoreError, ClientError

from tramplin.core.errors import StorageError
from tramplin.models.enums import AssetMime

if TYPE_CHECKING:
    from types_aiobotocore_s3 import S3Client

logger = logging.getLogger(__name__)


@contextmanager
def _storage_errors() -> Iterator[None]:
    try:
        yield
    except (BotoCoreError, ClientError) as exc:
        logger.warning("s3 error: %s", exc)
        raise StorageError from exc


class S3Storage:
    def __init__(self, client: "S3Client", bucket: str, public_base_url: str) -> None:
        self._client = client
        self._bucket = bucket
        self._public_base_url = public_base_url

    def public_url(self, key: str) -> str:
        return f"{self._public_base_url}/{key}"

    async def upload(self, key: str, body: bytes, mime: AssetMime) -> str:
        with _storage_errors():
            await self._client.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=body,
                ContentType=mime.value,
            )
        return self.public_url(key)

    async def delete(self, key: str) -> None:
        with _storage_errors():
            await self._client.delete_object(Bucket=self._bucket, Key=key)
