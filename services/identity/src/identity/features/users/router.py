"""User endpoints — profile, update, password change."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from identity.features.dependencies import get_current_user, get_user_repo
from identity.features.users.repository import UserRepository
from identity.features.users.schemas import ChangePasswordRequest, UserResponse, UserUpdateRequest
from skyrict_common.exceptions import UserNotFoundError
from skyrict_common.schemas import ResponseEnvelope

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=ResponseEnvelope[UserResponse])
async def get_my_profile(
    current_user: dict[str, Any] = Depends(get_current_user),
    user_repo: UserRepository = Depends(get_user_repo),
) -> ResponseEnvelope[UserResponse]:
    """Get the current user's profile."""
    user = await user_repo.get_by_id(current_user["user_id"])
    if user is None:
        raise UserNotFoundError()
    return ResponseEnvelope(data=UserResponse.model_validate(user))


@router.put("/me", response_model=ResponseEnvelope[UserResponse])
async def update_my_profile(
    body: UserUpdateRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
    user_repo: UserRepository = Depends(get_user_repo),
) -> ResponseEnvelope[UserResponse]:
    """Update the current user's profile."""
    user = await user_repo.get_by_id(current_user["user_id"])
    if user is None:
        raise UserNotFoundError()
    if body.full_name is not None:
        user.full_name = body.full_name
    if body.email is not None:
        user.email = body.email
    await user_repo.commit()
    return ResponseEnvelope(data=UserResponse.model_validate(user), message="Profile updated")


@router.post("/me/password")
async def change_password(
    body: ChangePasswordRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
    user_repo: UserRepository = Depends(get_user_repo),
) -> ResponseEnvelope[None]:
    """Change the current user's password."""
    from identity.core.security import hash_password, verify_password

    user = await user_repo.get_by_id(current_user["user_id"])
    if user is None:
        raise UserNotFoundError()
    if not verify_password(body.current_password, user.password_hash):
        from skyrict_common.exceptions import InvalidPasswordError

        raise InvalidPasswordError("Current password is incorrect")

    user.password_hash = hash_password(body.new_password)
    await user_repo.commit()
    return ResponseEnvelope(message="Password changed successfully")
