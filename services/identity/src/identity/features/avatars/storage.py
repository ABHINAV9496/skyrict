"""Avatar storage - filesystem (local) and S3 backends behind one port.

Keys are always the tenant-scoped relative path ``{tenant_id}/{user_id}/{filename}``.
Implementations reject any key that escapes their namespace.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import anyio

from identity.core.config import settings


class AvatarStoragePort(ABC):
    """Blob storage contract for avatar files."""

    @abstractmethod
    async def put(self, key: str, data: bytes, content_type: str) -> None:
        """Store ``data`` at ``key``."""

    @abstractmethod
    async def get(self, key: str) -> bytes | None:
        """Return the bytes at ``key``, or None when absent."""

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Remove the object at ``key`` (no-op when absent)."""


class LocalAvatarStorage(AvatarStoragePort):
    """Filesystem-backed avatar storage rooted at ``base_dir``."""

    def __init__(self, base_dir: str | Path) -> None:
        self.base_dir = Path(base_dir)

    def _resolve(self, key: str) -> Path:
        if not key or key.startswith("/") or ".." in key.replace("\\", "/").split("/"):
            raise ValueError(f"Invalid avatar storage key: {key!r}")
        path = self.base_dir / key
        try:
            path.resolve().relative_to(self.base_dir.resolve())
        except ValueError as exc:
            raise ValueError(f"Invalid avatar storage key: {key!r}") from exc
        return path

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        path = self._resolve(key)
        await anyio.to_thread.run_sync(self._write, path, data)

    async def get(self, key: str) -> bytes | None:
        path = self._resolve(key)
        return await anyio.to_thread.run_sync(self._read, path)

    async def delete(self, key: str) -> None:
        path = self._resolve(key)
        await anyio.to_thread.run_sync(self._unlink, path)

    def _write(self, path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def _read(self, path: Path) -> bytes | None:
        if not path.is_file():
            return None
        return path.read_bytes()

    def _unlink(self, path: Path) -> None:
        if path.is_file():
            path.unlink()


class S3AvatarStorage(AvatarStoragePort):
    """S3-backed avatar storage under ``prefix`` in ``bucket``.

    ``boto3`` is imported lazily inside the methods so the identity service
    runs without it unless the S3 backend is selected.
    """

    def __init__(self, *, bucket: str, prefix: str, region: str) -> None:
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self.region = region
        self._client: Any | None = None

    def _key(self, key: str) -> str:
        if not key or key.startswith("/") or ".." in key.replace("\\", "/").split("/"):
            raise ValueError(f"Invalid avatar storage key: {key!r}")
        return f"{self.prefix}/{key}"

    def _get_client(self) -> Any:
        if self._client is None:
            import boto3

            self._client = boto3.client("s3", region_name=self.region or None)
        return self._client

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        client = self._get_client()
        await anyio.to_thread.run_sync(
            lambda: client.put_object(
                Bucket=self.bucket,
                Key=self._key(key),
                Body=data,
                ContentType=content_type,
            )
        )

    async def get(self, key: str) -> bytes | None:
        client = self._get_client()
        try:
            response = await anyio.to_thread.run_sync(
                lambda: client.get_object(Bucket=self.bucket, Key=self._key(key))
            )
        except Exception:  # missing object -> None
            return None
        body = response["Body"]
        return await anyio.to_thread.run_sync(body.read)

    async def delete(self, key: str) -> None:
        client = self._get_client()
        await anyio.to_thread.run_sync(
            lambda: client.delete_object(Bucket=self.bucket, Key=self._key(key))
        )


def build_avatar_storage() -> AvatarStoragePort:
    """Construct the avatar storage backend selected by configuration."""
    backend = settings.AVATAR_STORAGE_BACKEND.strip().lower()
    if backend == "s3":
        if not settings.AVATAR_S3_BUCKET.strip():
            raise RuntimeError("AVATAR_STORAGE_BACKEND=s3 requires AVATAR_S3_BUCKET to be set")
        return S3AvatarStorage(
            bucket=settings.AVATAR_S3_BUCKET,
            prefix=settings.AVATAR_S3_PREFIX,
            region=settings.AVATAR_S3_REGION,
        )
    return LocalAvatarStorage(settings.AVATAR_STORAGE_LOCAL_DIR)
