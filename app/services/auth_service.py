from sqlalchemy.orm import Session
from fastapi import HTTPException, status, Response

from app.models.users import User, UserRole
from app.models.token import RefreshToken
from app.core.security import hash_password, verify_password
from app.core.jwt import create_access_token, create_refresh_token, decode_token
from app.core.config import settings


# ── Cookie configuration ────────────────────────────────────────────────────

ACCESS_COOKIE = "access_token"
REFRESH_COOKIE = "refresh_token"

COOKIE_DEFAULTS = dict(
    httponly=True,  # JavaScript cannot read this cookie — blocks XSS theft
    secure=not settings.DEBUG,  # Only sent over HTTPS in production
    samesite="lax",  # Sent on same-site + top-level cross-site navigations (GET)
    # Blocks CSRF on state-mutating requests (POST/PUT/DELETE)
)


def _set_auth_cookies(
    response: Response, access_token: str, refresh_token: str
) -> None:
    response.set_cookie(
        key=ACCESS_COOKIE,
        value=access_token,
        max_age=15 * 60,  # 15 minutes in seconds
        **COOKIE_DEFAULTS,
    )
    response.set_cookie(
        key=REFRESH_COOKIE,
        value=refresh_token,
        max_age=7 * 24 * 60 * 60,  # 7 days in seconds
        path="/api/v1/auth/",  # Scoped to auth endpoints
        **COOKIE_DEFAULTS,
    )


def _clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(ACCESS_COOKIE)
    response.delete_cookie(REFRESH_COOKIE, path="/api/v1/auth/")


# ── Register ────────────────────────────────────────────────────────────────


def register_user(
    name: str, email: str, password: str, db: Session, response: Response
) -> dict:
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        )

    user = User(
        name=name,
        email=email,
        password_hash=hash_password(password),
        role=UserRole.developer,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    _issue_tokens(user, db, response)

    return {"message": "Account created successfully", "user_id": user.id}


# ── Login ───────────────────────────────────────────────────────────────────


def login_user(email: str, password: str, db: Session, response: Response) -> dict:
    user = db.query(User).filter(User.email == email).first()

    # Always run verify_password even if user not found — prevents timing attacks
    # that reveal whether an email is registered
    dummy_hash = "$argon2id$v=19$m=65536,t=3,p=4$fakefakefake"
    valid = verify_password(password, user.password_hash if user else dummy_hash)

    if not user or not valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if user.totp_secret:
        # 2FA is enabled — don't issue full session yet.
        # Return a short-lived challenge token so the client knows to
        # redirect to the TOTP verification screen.
        challenge_token = create_access_token(
            {"sub": str(user.id), "scope": "totp_challenge"}
        )
        return {"requires_2fa": True, "challenge_token": challenge_token}

    _issue_tokens(user, db, response)
    return {"message": "Logged in successfully"}


# ── Refresh ─────────────────────────────────────────────────────────────────


def refresh_session(refresh_token: str, db: Session, response: Response) -> dict:
    payload = decode_token(refresh_token, expected_type="refresh")
    user_id = int(payload["sub"])

    db_token = (
        db.query(RefreshToken).filter(RefreshToken.token == refresh_token).first()
    )

    if not db_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Session not found"
        )

    if db_token.revoked:
        # Token reuse detected — someone is trying to use an already-revoked token.
        # This could mean theft. Revoke ALL sessions for this user immediately.
        db.query(RefreshToken).filter(RefreshToken.user_id == user_id).update(
            {"revoked": True}
        )
        db.commit()
        _clear_auth_cookies(response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session has been revoked. Please log in again.",
        )

    # Rotate: revoke old token, issue new pair
    db_token.revoked = True
    db.commit()

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found"
        )

    _issue_tokens(user, db, response)
    return {"message": "Session refreshed"}


# ── Logout ──────────────────────────────────────────────────────────────────


def logout_user(refresh_token: str | None, db: Session, response: Response) -> dict:
    if refresh_token:
        db.query(RefreshToken).filter(RefreshToken.token == refresh_token).update(
            {"revoked": True}
        )
        db.commit()

    _clear_auth_cookies(response)
    return {"message": "Logged out successfully"}


# ── Internal helper ─────────────────────────────────────────────────────────


def _issue_tokens(user: User, db: Session, response: Response) -> None:
    """Create an access+refresh pair, store the refresh token, set cookies."""
    access_token = create_access_token({"sub": str(user.id), "role": user.role.value})
    refresh_token, expires_at = create_refresh_token({"sub": str(user.id)})

    db_token = RefreshToken(
        token=refresh_token,
        user_id=user.id,
        expires_at=expires_at,
    )
    db.add(db_token)
    db.commit()

    _set_auth_cookies(response, access_token, refresh_token)
