import base64
import hashlib
import hmac
import secrets
import time

import pyotp
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

TOTP_INTERVAL_SECONDS = 30
TOTP_VALID_WINDOW = 1
RECOVERY_CODE_COUNT = 10


def generate_totp_secret() -> str:
    return pyotp.random_base32()


def encrypt_totp_secret(secret: str) -> str:
    return _fernet().encrypt(secret.encode("utf-8")).decode("utf-8")


def decrypt_totp_secret(secret: str) -> str:
    try:
        return _fernet().decrypt(secret.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        # Backward-compatible with any plaintext secrets created before this change.
        return secret


def build_otpauth_url(email: str, secret: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(
        name=email,
        issuer_name=settings.MFA_ISSUER_NAME,
    )


def verify_totp_code(
    secret: str,
    code: str,
    last_used_counter: int | None = None,
) -> int | None:
    normalized = "".join(code.split())
    if not normalized.isdigit() or len(normalized) != 6:
        return None

    totp = pyotp.TOTP(secret, interval=TOTP_INTERVAL_SECONDS)
    current_counter = int(time.time()) // TOTP_INTERVAL_SECONDS

    for offset in range(-TOTP_VALID_WINDOW, TOTP_VALID_WINDOW + 1):
        counter = current_counter + offset
        if last_used_counter is not None and counter <= last_used_counter:
            continue
        expected = totp.at(counter * TOTP_INTERVAL_SECONDS)
        if hmac.compare_digest(expected, normalized):
            return counter

    return None


def generate_recovery_codes() -> list[str]:
    return [_format_recovery_code(secrets.token_hex(8)) for _ in range(RECOVERY_CODE_COUNT)]


def normalize_recovery_code(code: str) -> str:
    return code.replace("-", "").replace(" ", "").strip().lower()


def _format_recovery_code(code: str) -> str:
    return "-".join(code[i : i + 4] for i in range(0, len(code), 4))


def _fernet() -> Fernet:
    key_source = settings.MFA_ENCRYPTION_KEY or settings.JWT_SECRET
    digest = hashlib.sha256(key_source.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))
