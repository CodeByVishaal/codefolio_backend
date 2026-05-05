from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.schemas.auth import (
    MFADisableRequest,
    MFAEnableRequest,
    MFARecoveryCodesResponse,
    MFASetupRequest,
    MFASetupResponse,
    MFAStatusResponse,
    MFAVerifyRequest,
    UserLogin,
    UserRegister,
)
from app.services.auth_service import (
    register_user,
    login_user,
    refresh_session,
    logout_user,
)
from app.services import mfa_service
from app.core.deps import get_current_user, get_db, get_refresh_token
from app.models.users import User

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
    - If MFA is enabled: returns { requires_mfa: true, challenge_token: "..." }
    - Otherwise: sets auth cookies and returns { message: "Logged in successfully" }
    """
    return login_user(data.email, data.password, db, response)


@router.get("/mfa/status", response_model=MFAStatusResponse)
def mfa_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return MFA state for the current account."""
    return mfa_service.get_mfa_status(current_user, db)


@router.post("/mfa/setup", response_model=MFASetupResponse)
def setup_mfa(
    data: MFASetupRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Start authenticator-app MFA setup.
    Returns an otpauth URL for QR generation on the frontend.
    """
    return mfa_service.start_mfa_setup(data.password, current_user, db)


@router.post("/mfa/enable", response_model=MFARecoveryCodesResponse)
def enable_mfa(
    data: MFAEnableRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Verify the first authenticator code and return one-time recovery codes."""
    return mfa_service.enable_mfa(data.password, data.code, current_user, db)


@router.post("/mfa/verify")
def verify_mfa(
    data: MFAVerifyRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    """
    Complete an MFA login challenge and set auth cookies.
    Accepts either a TOTP code or a one-time recovery code.
    """
    return mfa_service.verify_mfa_challenge(
        data.challenge_token,
        data.code,
        data.recovery_code,
        db,
        response,
    )


@router.post("/mfa/recovery-codes", response_model=MFARecoveryCodesResponse)
def regenerate_recovery_codes(
    data: MFADisableRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Replace all recovery codes and return the new set once."""
    return mfa_service.regenerate_recovery_codes(
        data.password,
        data.code,
        data.recovery_code,
        current_user,
        db,
    )


@router.post("/mfa/disable")
def disable_mfa(
    data: MFADisableRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Disable MFA after password plus a current MFA factor."""
    return mfa_service.disable_mfa(
        data.password,
        data.code,
        data.recovery_code,
        current_user,
        db,
    )


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
