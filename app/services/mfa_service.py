from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Response, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.jwt import decode_token
from app.core.mfa import (
    build_otpauth_url,
    decrypt_totp_secret,
    encrypt_totp_secret,
    generate_recovery_codes,
    generate_totp_secret,
    normalize_recovery_code,
    verify_totp_code,
)
from app.core.security import hash_password, verify_password
from app.models.mfa import MFARecoveryCode
from app.models.users import User
from app.services.auth_service import _issue_tokens


def get_mfa_status(user: User, db: Session) -> dict:
    remaining_codes = (
        db.query(MFARecoveryCode)
        .filter(MFARecoveryCode.user_id == user.id, MFARecoveryCode.used_at.is_(None))
        .count()
    )
    return {
        "enabled": bool(user.mfa_enabled),
        "recovery_codes_remaining": remaining_codes if user.mfa_enabled else 0,
    }


def start_mfa_setup(password: str, user: User, db: Session) -> dict:
    _require_password(user, password)

    if user.mfa_enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="MFA is already enabled",
        )

    secret = generate_totp_secret()
    user.totp_secret = encrypt_totp_secret(secret)
    user.mfa_last_used_counter = None
    user.mfa_failed_attempts = 0
    user.mfa_locked_until = None
    db.commit()

    return {
        "secret": secret,
        "otpauth_url": build_otpauth_url(user.email, secret),
        "issuer": settings.MFA_ISSUER_NAME,
    }


def enable_mfa(password: str, code: str, user: User, db: Session) -> dict:
    _require_password(user, password)

    if user.mfa_enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="MFA is already enabled",
        )
    if not user.totp_secret:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Start MFA setup before enabling it",
        )

    secret = decrypt_totp_secret(user.totp_secret)
    counter = verify_totp_code(secret, code)
    if counter is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid MFA code",
        )

    recovery_codes = _replace_recovery_codes(user, db)
    user.mfa_enabled = True
    user.mfa_last_used_counter = counter
    user.mfa_failed_attempts = 0
    user.mfa_locked_until = None
    db.commit()

    return {
        "message": "MFA enabled successfully",
        "recovery_codes": recovery_codes,
    }


def verify_mfa_challenge(
    challenge_token: str,
    code: str | None,
    recovery_code: str | None,
    db: Session,
    response: Response,
) -> dict:
    payload = decode_token(challenge_token, expected_type="access")
    if payload.get("scope") not in {"mfa_challenge", "totp_challenge"}:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid MFA challenge",
        )

    user = _get_user_from_payload(payload, db)
    _require_mfa_enabled(user)
    used_recovery_code = _verify_mfa_factor(user, db, code, recovery_code)

    _issue_tokens(user, db, response)
    message = "Logged in successfully"
    if used_recovery_code:
        remaining = get_mfa_status(user, db)["recovery_codes_remaining"]
        message = f"Logged in successfully. Recovery codes remaining: {remaining}"
    return {"message": message}


def disable_mfa(
    password: str,
    code: str | None,
    recovery_code: str | None,
    user: User,
    db: Session,
) -> dict:
    _require_password(user, password)
    _require_mfa_enabled(user)
    _verify_mfa_factor(user, db, code, recovery_code)

    db.query(MFARecoveryCode).filter(MFARecoveryCode.user_id == user.id).delete()
    user.totp_secret = None
    user.mfa_enabled = False
    user.mfa_last_used_counter = None
    user.mfa_failed_attempts = 0
    user.mfa_locked_until = None
    db.commit()

    return {"message": "MFA disabled successfully"}


def regenerate_recovery_codes(
    password: str,
    code: str | None,
    recovery_code: str | None,
    user: User,
    db: Session,
) -> dict:
    _require_password(user, password)
    _require_mfa_enabled(user)
    _verify_mfa_factor(user, db, code, recovery_code)
    recovery_codes = _replace_recovery_codes(user, db)
    db.commit()
    return {
        "message": "Recovery codes regenerated successfully",
        "recovery_codes": recovery_codes,
    }


def _verify_mfa_factor(
    user: User,
    db: Session,
    code: str | None,
    recovery_code: str | None,
) -> bool:
    if bool(code) == bool(recovery_code):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide either an MFA code or a recovery code",
        )

    _enforce_mfa_lock(user)

    if code:
        secret = decrypt_totp_secret(user.totp_secret)
        counter = verify_totp_code(secret, code, user.mfa_last_used_counter)
        if counter is not None:
            user.mfa_last_used_counter = counter
            _reset_mfa_failures(user)
            db.commit()
            return False

    if recovery_code and _consume_recovery_code(user, db, recovery_code):
        _reset_mfa_failures(user)
        db.commit()
        return True

    _record_mfa_failure(user, db)
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid MFA code",
    )


def _consume_recovery_code(user: User, db: Session, recovery_code: str) -> bool:
    normalized = normalize_recovery_code(recovery_code)
    if len(normalized) != 16:
        return False

    recovery_codes = (
        db.query(MFARecoveryCode)
        .filter(MFARecoveryCode.user_id == user.id, MFARecoveryCode.used_at.is_(None))
        .all()
    )

    for stored_code in recovery_codes:
        if verify_password(normalized, stored_code.code_hash):
            stored_code.used_at = datetime.now(timezone.utc)
            return True

    return False


def _replace_recovery_codes(user: User, db: Session) -> list[str]:
    db.query(MFARecoveryCode).filter(MFARecoveryCode.user_id == user.id).delete()

    recovery_codes = generate_recovery_codes()
    for recovery_code in recovery_codes:
        db.add(
            MFARecoveryCode(
                user_id=user.id,
                code_hash=hash_password(normalize_recovery_code(recovery_code)),
            )
        )
    return recovery_codes


def _record_mfa_failure(user: User, db: Session) -> None:
    user.mfa_failed_attempts = (user.mfa_failed_attempts or 0) + 1
    if user.mfa_failed_attempts >= settings.MFA_MAX_FAILED_ATTEMPTS:
        user.mfa_locked_until = datetime.now(timezone.utc) + timedelta(
            minutes=settings.MFA_LOCK_MINUTES
        )
    db.commit()


def _reset_mfa_failures(user: User) -> None:
    user.mfa_failed_attempts = 0
    user.mfa_locked_until = None


def _enforce_mfa_lock(user: User) -> None:
    locked_until = user.mfa_locked_until
    if locked_until and locked_until.tzinfo is None:
        locked_until = locked_until.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    if locked_until and locked_until > now:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many MFA attempts. Please try again later.",
        )
    if locked_until and locked_until <= now:
        _reset_mfa_failures(user)


def _require_password(user: User, password: str) -> None:
    if not verify_password(password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )


def _require_mfa_enabled(user: User) -> None:
    if not user.mfa_enabled or not user.totp_secret:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="MFA is not enabled",
        )


def _get_user_from_payload(payload: dict, db: Session) -> User:
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )

    user = db.query(User).filter(User.id == int(user_id)).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )
    return user
