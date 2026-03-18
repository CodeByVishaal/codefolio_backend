from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.schemas.auth import UserRegister, UserLogin
from app.services.auth_service import (
    register_user,
    login_user,
    refresh_session,
    logout_user,
)
from app.core.deps import get_db, get_refresh_token

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", status_code=201)
def register(user: UserRegister, response: Response, db: Session = Depends(get_db)):
    """
    Register a new developer account.
    Sets access_token and refresh_token cookies on success.
    """
    return register_user(user.name, user.email, user.password, db, response)


@router.post("/login")
def login(data: UserLogin, response: Response, db: Session = Depends(get_db)):
    """
    Log in with email and password.
    - If 2FA is enabled: returns { requires_2fa: true, challenge_token: "..." }
    - Otherwise: sets auth cookies and returns { message: "Logged in successfully" }
    """
    return login_user(data.email, data.password, db, response)


@router.post("/refresh")
def refresh(
    response: Response,
    db: Session = Depends(get_db),
    refresh_token: str | None = Depends(get_refresh_token),
):
    """
    Exchange a valid refresh_token cookie for a new access+refresh pair.
    Old refresh token is revoked (rotation). Detects and responds to reuse attacks.
    """
    if not refresh_token:
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="No refresh token"
        )
    return refresh_session(refresh_token, db, response)


@router.post("/logout")
def logout(
    response: Response,
    db: Session = Depends(get_db),
    refresh_token: str | None = Depends(get_refresh_token),
):
    """
    Revoke the current session and clear auth cookies.
    Safe to call even if already logged out.
    """
    return logout_user(refresh_token, db, response)
