"""User endpoints — profile, update, password change."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from identity.api.deps import get_current_user, get_user_service
from identity.features.users.schemas import ChangePasswordRequest, UserResponse, UserUpdateRequest
from identity.features.users.service import UserService
from skyrict_common.schemas import ResponseEnvelope

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=ResponseEnvelope[UserResponse])
async def get_my_profile(
    current_user: dict[str, Any] = Depends(get_current_user),
    user_svc: UserService = Depends(get_user_service),
) -> ResponseEnvelope[UserResponse]:
    """Get the current user's profile."""
    user = await user_svc.get_profile(current_user["user_id"])
    return ResponseEnvelope(data=UserResponse.model_validate(user))


@router.put("/me", response_model=ResponseEnvelope[UserResponse])
async def update_my_profile(
    body: UserUpdateRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
    user_svc: UserService = Depends(get_user_service),
) -> ResponseEnvelope[UserResponse]:
    """Update the current user's profile."""
    user = await user_svc.update_profile(current_user["user_id"], body)
    return ResponseEnvelope(data=UserResponse.model_validate(user), message="Profile updated")


@router.post("/me/password")
async def change_password(
    body: ChangePasswordRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
    user_svc: UserService = Depends(get_user_service),
) -> ResponseEnvelope[None]:
    """Change the current user's password."""
    await user_svc.change_password(
        current_user["user_id"], body.current_password, body.new_password
    )
    return ResponseEnvelope(message="Password changed successfully")
