from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.db.sessions import SessionLocal
from app.models.user import User, UserRole
from app.core.jwt import decode_token


# ── Database ─────────────────────────────────────────────────────────────────


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── Token extraction ──────────────────────────────────────────────────────────


def _get_access_token(request: Request) -> str:
    """Pull the access token from the httpOnly cookie."""
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated. Please log in.",
        )
    return token


def _get_refresh_token(request: Request) -> str | None:
    """Pull the refresh token from the httpOnly cookie (may be absent)."""
    return request.cookies.get("refresh_token")


# ── Current user ──────────────────────────────────────────────────────────────


def get_current_user(
    token: str = Depends(_get_access_token),
    db: Session = Depends(get_db),
) -> User:
    """
    Decode the access token cookie and return the authenticated User.
    Raises 401 if the token is missing, invalid, expired, or the user doesn't exist.
    """
    payload = decode_token(token, expected_type="access")

    # Reject tokens issued for the 2FA challenge — they're not full sessions
    if payload.get("scope") == "totp_challenge":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="2FA verification required",
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload"
        )

    user = db.query(User).filter(User.id == int(user_id)).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found"
        )

    return user


# ── Role-based access control ─────────────────────────────────────────────────


def require_verified(user: User = Depends(get_current_user)) -> User:
    """User must have verified their email."""
    if not user.is_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Please verify your email address to access this resource",
        )
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    """User must have the admin role."""
    if user.role != UserRole.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user


def require_developer(user: User = Depends(get_current_user)) -> User:
    """User must be a developer or admin (any authenticated user)."""
    if user.role not in (UserRole.developer, UserRole.admin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Developer access required",
        )
    return user


# ── Convenience re-export ─────────────────────────────────────────────────────
# Routers can import everything they need from one place
get_refresh_token = _get_refresh_token
