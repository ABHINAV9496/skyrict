"""Avatar endpoints — serve images publicly, upload/remove the current user's.

Serving (``GET /avatars/{user_id}/{filename}``) is deliberately unauthenticated:
``<img>`` tags cannot send Authorization headers. Tenant isolation comes from
the middleware-resolved ``TenantContext`` (the request must already be routed
to the owning tenant) plus a per-request tenant cross-check in the service.

Upload and removal are authenticated like any other state-changing route.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Depends, File, UploadFile
from starlette.responses import Response

from identity.api.deps import get_avatar_service, get_current_user
from identity.core.tenant_context import TenantContext
from identity.features.avatars.processing import AVATAR_MIME
from identity.features.users.schemas import UserResponse
from skyrict_common.exceptions import NotFoundError
from skyrict_common.schemas import ResponseEnvelope

if TYPE_CHECKING:
    from identity.features.avatars.service import AvatarService

router = APIRouter(prefix="/avatars", tags=["avatars"])


@router.put("/me", response_model=ResponseEnvelope[UserResponse])
async def upload_avatar(
    avatar: Annotated[UploadFile, File()],
    current_user: dict[str, Any] = Depends(get_current_user),
    avatar_service: AvatarService = Depends(get_avatar_service),
) -> ResponseEnvelope[UserResponse]:
    """Upload the current user's avatar (image is normalized to 256x256 WebP)."""
    user = await avatar_service.upload(
        user_id=current_user["user_id"],
        tenant_id=current_user["tenant_id"],
        data=await avatar.read(),
    )
    return ResponseEnvelope(data=UserResponse.model_validate(user), message="Avatar updated")


@router.delete("/me", response_model=ResponseEnvelope[UserResponse])
async def remove_avatar(
    current_user: dict[str, Any] = Depends(get_current_user),
    avatar_service: AvatarService = Depends(get_avatar_service),
) -> ResponseEnvelope[UserResponse]:
    """Remove the current user's avatar."""
    user = await avatar_service.remove(
        user_id=current_user["user_id"],
        tenant_id=current_user["tenant_id"],
    )
    return ResponseEnvelope(data=UserResponse.model_validate(user), message="Avatar removed")


@router.get("/{user_id}/{filename}")
async def serve_avatar(
    user_id: str,
    filename: str,
    avatar_service: AvatarService = Depends(get_avatar_service),
) -> Response:
    """Serve an avatar image (tenant-scoped, cacheable, no auth headers)."""
    try:
        uuid.UUID(user_id)
    except ValueError as exc:
        raise NotFoundError("Avatar not found") from exc

    data = await avatar_service.fetch(
        user_id=user_id,
        filename=filename,
        tenant_id=str(TenantContext.get()),
    )
    if data is None:
        raise NotFoundError("Avatar not found")

    return Response(
        content=data,
        media_type=AVATAR_MIME,
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )
