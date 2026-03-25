from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_db, get_current_user
from app.models.users import User
from app.schemas.user import MeResponse, PublicProfileResponse
from app.services import user_service

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=MeResponse)
def get_me(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Returns the full private profile for the currently logged-in user.
    Includes email, role, verification status, and all stats.
    Requires authentication.
    """
    return user_service.get_me(current_user, db)


@router.get("/{user_id}/profile", response_model=PublicProfileResponse)
def get_public_profile(
    user_id: int,
    db: Session = Depends(get_db),
):
    """
    Returns the public portfolio page for any user.
    No authentication required — this is a shareable public URL.
    Only shows public projects, public journal entries, and aggregate stats.
    """
    return user_service.get_public_profile(user_id, db)
