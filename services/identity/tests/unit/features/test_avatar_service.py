"""Unit tests for the avatar feature — processing, storage, and service."""

from __future__ import annotations

import io
import uuid

import pytest
from PIL import Image

from identity.domain.entities import User
from identity.features.avatars.processing import normalize_avatar
from identity.features.avatars.service import AvatarService, is_valid_filename
from identity.features.avatars.storage import LocalAvatarStorage
from skyrict_common.exceptions import ValidationError


def _make_png(width: int = 64, height: int = 64) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (200, 60, 90)).save(buffer, format="PNG")
    return buffer.getvalue()


class FakeStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.content_types: dict[str, str] = {}

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        self.objects[key] = data
        self.content_types[key] = content_type

    async def get(self, key: str) -> bytes | None:
        return self.objects.get(key)

    async def delete(self, key: str) -> None:
        self.objects.pop(key, None)
        self.content_types.pop(key, None)


class FakeUserRepo:
    def __init__(self) -> None:
        self.users: dict[uuid.UUID, User] = {}
        self.updates: list[tuple[uuid.UUID, str | None]] = []

    async def get_by_id(self, user_id: str | uuid.UUID) -> User | None:
        return self.users.get(uuid.UUID(str(user_id)))

    async def update_avatar(self, user_id: str | uuid.UUID, avatar_url: str | None) -> User:
        key = uuid.UUID(str(user_id))
        user = self.users[key]
        user.avatar_url = avatar_url
        self.updates.append((key, avatar_url))
        return user


def _seed_user(repo: FakeUserRepo, *, tenant_id: uuid.UUID) -> uuid.UUID:
    user_id = uuid.uuid4()
    repo.users[user_id] = User(
        tenant_id=tenant_id,
        email="owner@test.com",
        password_hash="hash",
        full_name="Owner",
        is_verified=True,
    )
    return user_id


class TestNormalizeAvatar:
    def test_normalizes_png_to_webp(self) -> None:
        result = normalize_avatar(_make_png())
        assert result.startswith(b"RIFF")
        image = Image.open(io.BytesIO(result))
        assert image.format == "WEBP"
        assert image.size == (256, 256)

    def test_rejects_non_image(self) -> None:
        with pytest.raises(ValidationError):
            normalize_avatar(b"this is definitely not an image")

    def test_rejects_empty(self) -> None:
        with pytest.raises(ValidationError):
            normalize_avatar(b"")

    def test_rejects_unsupported_format(self) -> None:
        buffer = io.BytesIO()
        Image.new("L", (32, 32), 128).save(buffer, format="BMP")
        with pytest.raises(ValidationError):
            normalize_avatar(buffer.getvalue())


class TestFilenameValidation:
    def test_accepts_generated_filename(self) -> None:
        assert is_valid_filename(f"{'a' * 32}.webp") is True

    def test_rejects_path_traversal(self) -> None:
        assert is_valid_filename("../secret.webp") is False
        assert is_valid_filename("not-a-valid-name.webp") is False
        assert is_valid_filename(f"{'a' * 32}.png") is False


class TestLocalStorage:
    async def test_roundtrip(self, tmp_path) -> None:
        storage = LocalAvatarStorage(tmp_path)
        await storage.put("tenant/uid/abc.webp", b"data", "image/webp")
        assert await storage.get("tenant/uid/abc.webp") == b"data"
        await storage.delete("tenant/uid/abc.webp")
        assert await storage.get("tenant/uid/abc.webp") is None

    async def test_missing_key_returns_none(self, tmp_path) -> None:
        storage = LocalAvatarStorage(tmp_path)
        assert await storage.get("tenant/uid/nope.webp") is None

    async def test_rejects_traversal(self, tmp_path) -> None:
        storage = LocalAvatarStorage(tmp_path)
        with pytest.raises(ValueError):
            await storage.put("../escape.webp", b"data", "image/webp")
        with pytest.raises(ValueError):
            await storage.get("tenant/../escape.webp")


class TestAvatarService:
    async def test_upload_stores_blob_and_sets_avatar_url(self) -> None:
        storage = FakeStorage()
        repo = FakeUserRepo()
        tenant_id = uuid.uuid4()
        user_id = _seed_user(repo, tenant_id=tenant_id)
        service = AvatarService(storage, repo)

        user = await service.upload(
            user_id=str(user_id), tenant_id=str(tenant_id), data=_make_png()
        )

        assert user.avatar_url == f"{user_id}/{user.avatar_url.rsplit('/', 1)[-1]}"
        stored_key = f"{tenant_id}/{user_id}/{user.avatar_url.rsplit('/', 1)[-1]}"
        assert stored_key in storage.objects
        assert storage.content_types[stored_key] == "image/webp"

    async def test_upload_replaces_previous_avatar(self) -> None:
        storage = FakeStorage()
        repo = FakeUserRepo()
        tenant_id = uuid.uuid4()
        user_id = _seed_user(repo, tenant_id=tenant_id)
        service = AvatarService(storage, repo)

        first = await service.upload(
            user_id=str(user_id), tenant_id=str(tenant_id), data=_make_png()
        )
        first_key = f"{tenant_id}/{user_id}/{first.avatar_url.rsplit('/', 1)[-1]}"
        await service.upload(user_id=str(user_id), tenant_id=str(tenant_id), data=_make_png())

        assert first_key not in storage.objects
        assert len([k for k in storage.objects if str(user_id) in k]) == 1

    async def test_remove_clears_url_and_blob(self) -> None:
        storage = FakeStorage()
        repo = FakeUserRepo()
        tenant_id = uuid.uuid4()
        user_id = _seed_user(repo, tenant_id=tenant_id)
        service = AvatarService(storage, repo)
        await service.upload(user_id=str(user_id), tenant_id=str(tenant_id), data=_make_png())

        user = await service.remove(user_id=str(user_id), tenant_id=str(tenant_id))

        assert user.avatar_url is None
        assert not storage.objects

    async def test_fetch_returns_blob_for_owning_tenant(self) -> None:
        storage = FakeStorage()
        repo = FakeUserRepo()
        tenant_id = uuid.uuid4()
        user_id = _seed_user(repo, tenant_id=tenant_id)
        service = AvatarService(storage, repo)
        uploaded = await service.upload(
            user_id=str(user_id), tenant_id=str(tenant_id), data=_make_png()
        )
        filename = uploaded.avatar_url.rsplit("/", 1)[-1]

        data = await service.fetch(
            user_id=str(user_id), filename=filename, tenant_id=str(tenant_id)
        )
        assert data == storage.objects[f"{tenant_id}/{user_id}/{filename}"]

    async def test_fetch_denies_cross_tenant(self) -> None:
        storage = FakeStorage()
        repo = FakeUserRepo()
        tenant_id = uuid.uuid4()
        user_id = _seed_user(repo, tenant_id=tenant_id)
        service = AvatarService(storage, repo)
        uploaded = await service.upload(
            user_id=str(user_id), tenant_id=str(tenant_id), data=_make_png()
        )
        filename = uploaded.avatar_url.rsplit("/", 1)[-1]

        data = await service.fetch(
            user_id=str(user_id), filename=filename, tenant_id=str(uuid.uuid4())
        )
        assert data is None

    async def test_fetch_rejects_unknown_user(self) -> None:
        service = AvatarService(FakeStorage(), FakeUserRepo())
        data = await service.fetch(
            user_id=str(uuid.uuid4()),
            filename=f"{'a' * 32}.webp",
            tenant_id=str(uuid.uuid4()),
        )
        assert data is None

    async def test_attach_to_user_skips_invalid_upload(self) -> None:
        storage = FakeStorage()
        repo = FakeUserRepo()
        tenant_id = uuid.uuid4()
        user_id = _seed_user(repo, tenant_id=tenant_id)
        service = AvatarService(storage, repo)

        await service.attach_to_user(
            user_id=str(user_id), tenant_id=str(tenant_id), data=b"not an image"
        )

        assert not storage.objects
        assert repo.users[user_id].avatar_url is None
