"""Avatar service - orchestrates image processing, blob storage, and DB state.

No ORM or storage internals live here; persistence goes through the
``UserRepositoryPort`` and blobs through ``AvatarStoragePort``. ``avatar_url``
is stored as the relative path ``{user_id}/{filename}`` - the filename is a
random 32-hex WebP name, so paths are unguessable and the serving route can
validate them with a strict regex.
"""

from __future__ import annotations

import re
import uuid
from typing import TYPE_CHECKING

import structlog

from skyrict_common.exceptions import UserNotFoundError

if TYPE_CHECKING:
    from identity.domain.entities import User
    from identity.features.avatars.storage import AvatarStoragePort
    from identity.features.users.ports import UserRepositoryPort

_FILENAME_RE = re.compile(r"^[a-f0-9]{32}\.webp$")


def is_valid_filename(filename: str) -> bool:
    """True for generated avatar filenames only (no path components)."""
    return bool(_FILENAME_RE.fullmatch(filename))


class AvatarService:
    """Upload, remove, and fetch user avatars."""

    def __init__(self, storage: AvatarStoragePort, user_repo: UserRepositoryPort) -> None:
        self.storage = storage
        self.user_repo = user_repo

    def _key(self, tenant_id: str, user_id: str, filename: str) -> str:
        return f"{tenant_id}/{user_id}/{filename}"

    def _public_url(self, user_id: str, filename: str) -> str:
        return f"{user_id}/{filename}"

    async def upload(self, *, user_id: str, tenant_id: str, data: bytes) -> User:
        """Normalize ``data``, store it, and point the user's avatar_url at it.

        Replaces any previous avatar (deleted after the DB update commits).
        Raises ``UserNotFoundError`` for unknown users; validation errors from
        image processing propagate to the caller as ``ValidationError``.
        """
        from identity.features.avatars.processing import AVATAR_MIME, normalize_avatar

        user = await self.user_repo.get_by_id(user_id)
        if user is None:
            raise UserNotFoundError()
        old_url = user.avatar_url

        filename = f"{uuid.uuid4().hex}.webp"
        normalized = normalize_avatar(data)
        await self.storage.put(self._key(tenant_id, user_id, filename), normalized, AVATAR_MIME)
        updated = await self.user_repo.update_avatar(user_id, self._public_url(user_id, filename))

        if old_url:
            await self.storage.delete(self._key(tenant_id, user_id, old_url.rsplit("/", 1)[-1]))
        return updated

    async def remove(self, *, user_id: str, tenant_id: str) -> User:
        """Clear the user's avatar_url and delete the stored blob."""
        user = await self.user_repo.get_by_id(user_id)
        if user is None:
            raise UserNotFoundError()
        old_url = user.avatar_url
        updated = await self.user_repo.update_avatar(user_id, None)
        if old_url:
            await self.storage.delete(self._key(tenant_id, user_id, old_url.rsplit("/", 1)[-1]))
        return updated

    async def attach_to_user(self, *, user_id: str, tenant_id: str, data: bytes) -> None:
        """Store a normalized avatar for a newly-created user without failing.

        Used by self-service flows (invitation accept) where the avatar is
        optional decoration: invalid images are logged and skipped so a bad
        upload never blocks account creation. ``user_id`` must already exist.
        """
        from identity.features.avatars.processing import AVATAR_MIME, normalize_avatar
        from skyrict_common.exceptions import ValidationError

        logger = structlog.get_logger("identity.avatars")
        try:
            normalized = normalize_avatar(data)
        except ValidationError:
            logger.warning("avatar_skipped_invalid_upload", user_id=user_id)
            return
        filename = f"{uuid.uuid4().hex}.webp"
        await self.storage.put(self._key(tenant_id, user_id, filename), normalized, AVATAR_MIME)
        await self.user_repo.update_avatar(user_id, self._public_url(user_id, filename))

    async def fetch(self, *, user_id: str, filename: str, tenant_id: str) -> bytes | None:
        """Return the avatar bytes for ``user_id`` if it belongs to ``tenant_id``.

        Returns None for unknown users, cross-tenant requests, or missing blobs
        so callers can 404 without leaking which case applied.
        """
        if not is_valid_filename(filename):
            return None
        user = await self.user_repo.get_by_id(user_id)
        if user is None or str(user.tenant_id) != str(tenant_id):
            return None
        return await self.storage.get(self._key(tenant_id, user_id, filename))
