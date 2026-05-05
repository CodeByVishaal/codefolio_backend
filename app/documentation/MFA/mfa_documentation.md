# CodeFolio MFA Documentation

This document explains the MFA feature added to CodeFolio: what it protects, how the workflow behaves, which files are involved, and what each function is responsible for.

MFA here means app-based TOTP authentication using apps such as Google Authenticator, Microsoft Authenticator, Authy, 1Password, or Bitwarden. The implementation also supports one-time recovery codes.

## Feature Purpose

The goal of MFA is to make account takeover harder even if a password is leaked.

Before MFA:

1. User submits email and password.
2. Backend verifies the password.
3. Backend issues auth cookies.

After MFA is enabled:

1. User submits email and password.
2. Backend verifies the password.
3. Backend does not issue full auth cookies yet.
4. Backend returns a short-lived MFA challenge token.
5. User submits a TOTP code or recovery code.
6. Backend verifies the MFA factor.
7. Backend issues auth cookies.

This creates a second gate between password verification and full session creation.

## Files Added Or Updated

| File | Purpose |
| --- | --- |
| `app/core/mfa.py` | Low-level TOTP, secret encryption, recovery-code formatting helpers. |
| `app/services/mfa_service.py` | Main business logic for setup, enable, verify, disable, lockout, and recovery codes. |
| `app/models/mfa.py` | SQLAlchemy model for one-time recovery codes. |
| `app/models/users.py` | Adds MFA-related fields to the existing `users` table. |
| `app/schemas/auth.py` | Adds request/response schemas for MFA endpoints. |
| `app/api/routes/auth.py` | Adds public API endpoints under `/api/v1/auth/mfa/...`. |
| `app/services/auth_service.py` | Updates login so MFA-enabled users receive a challenge token instead of auth cookies. |
| `app/core/jwt.py` | Allows custom expiry durations for short-lived challenge tokens. |
| `app/core/deps.py` | Prevents MFA challenge tokens from being accepted as normal auth tokens. |
| `app/core/config.py` | Adds MFA environment settings. |
| `migrations/versions/5b1f2c3d4e5a_add_mfa_support.py` | Database migration for MFA fields and recovery-code table. |
| `requirements.txt` | Adds `pyotp` and `cryptography`. |

## Environment Settings

The MFA settings live in `app/core/config.py`.

```python
MFA_ISSUER_NAME: str = "CodeFolio"
MFA_CHALLENGE_EXPIRE_MINUTES: int = 5
MFA_MAX_FAILED_ATTEMPTS: int = 5
MFA_LOCK_MINUTES: int = 5
MFA_ENCRYPTION_KEY: str | None = None
```

### `MFA_ISSUER_NAME`

This is the name shown inside authenticator apps. For example, Google Authenticator may show:

```text
CodeFolio: user@example.com
```

### `MFA_CHALLENGE_EXPIRE_MINUTES`

Controls how long the temporary challenge token is valid after password login.

Current default:

```text
5 minutes
```

This keeps the password-verified but MFA-unverified state short-lived.

### `MFA_MAX_FAILED_ATTEMPTS`

Controls how many invalid MFA attempts are allowed before temporary lockout.

Current default:

```text
5 attempts
```

### `MFA_LOCK_MINUTES`

Controls how long MFA verification is locked after too many failed attempts.

Current default:

```text
5 minutes
```

### `MFA_ENCRYPTION_KEY`

Optional secret used to encrypt TOTP secrets at rest.

If unset, the code falls back to `JWT_SECRET`. This makes deployment friendly because the app still works without immediately adding another Render environment variable.

Recommended production setup:

```env
MFA_ENCRYPTION_KEY=long-random-secret-value
```

Important: once real users enable MFA, changing this value will make existing encrypted TOTP secrets unreadable unless you migrate/re-encrypt them.

## Database Design

### New Fields On `users`

The `users` table now has these MFA fields:

| Column | Type | Purpose |
| --- | --- | --- |
| `totp_secret` | string nullable | Encrypted TOTP secret for the authenticator app. |
| `mfa_enabled` | boolean | Whether MFA is fully enabled for the user. |
| `mfa_last_used_counter` | integer nullable | Last accepted TOTP time-step counter, used to block replay. |
| `mfa_failed_attempts` | integer | Number of failed MFA attempts since last success/unlock. |
| `mfa_locked_until` | datetime nullable | Temporary lockout expiry time. |

### New Table: `mfa_recovery_codes`

Defined in `app/models/mfa.py`.

| Column | Type | Purpose |
| --- | --- | --- |
| `id` | integer | Primary key. |
| `user_id` | integer | Owner of the recovery code. Cascades on user delete. |
| `code_hash` | string | Argon2 hash of the recovery code. Plain recovery codes are never stored. |
| `created_at` | datetime | When the recovery code was generated. |
| `used_at` | datetime nullable | Set when the recovery code is consumed. |

Recovery codes are one-time use. After a code is used, `used_at` is set and it cannot be used again.

## API Endpoints

All routes are mounted under:

```text
/api/v1/auth
```

### `GET /mfa/status`

Returns whether MFA is enabled and how many unused recovery codes remain.

Authentication:

```text
Requires full login session.
```

Response:

```json
{
  "enabled": true,
  "recovery_codes_remaining": 9
}
```

### `POST /mfa/setup`

Starts MFA setup for the logged-in user.

Authentication:

```text
Requires full login session.
```

Body:

```json
{
  "password": "YourPassword1"
}
```

Response:

```json
{
  "secret": "BASE32SECRET",
  "otpauth_url": "otpauth://totp/CodeFolio:user@example.com?...",
  "issuer": "CodeFolio"
}
```

Purpose:

1. Confirms the user's password.
2. Generates a new TOTP secret.
3. Encrypts and stores the secret.
4. Returns the raw secret and `otpauth_url` so the frontend can show a QR code or manual setup key.

Important: setup does not enable MFA yet. MFA becomes enabled only after `/mfa/enable` verifies the first authenticator code.

### `POST /mfa/enable`

Completes MFA setup after the user enters the first valid TOTP code.

Authentication:

```text
Requires full login session.
```

Body:

```json
{
  "password": "YourPassword1",
  "code": "123456"
}
```

Response:

```json
{
  "message": "MFA enabled successfully",
  "recovery_codes": [
    "abcd-1234-ef56-7890"
  ]
}
```

Purpose:

1. Confirms the user's password.
2. Confirms setup has already generated a TOTP secret.
3. Verifies the 6-digit TOTP code.
4. Enables MFA.
5. Generates recovery codes.
6. Stores only recovery-code hashes.
7. Returns the plain recovery codes once.

### `POST /mfa/verify`

Completes login after password verification for an MFA-enabled account.

Authentication:

```text
Does not require existing full session.
Requires a valid challenge_token from /login.
```

Body using TOTP:

```json
{
  "challenge_token": "jwt-challenge-token",
  "code": "123456"
}
```

Body using recovery code:

```json
{
  "challenge_token": "jwt-challenge-token",
  "recovery_code": "abcd-1234-ef56-7890"
}
```

Response:

```json
{
  "message": "Logged in successfully"
}
```

Purpose:

1. Decodes the temporary challenge token.
2. Confirms the token scope is `mfa_challenge`.
3. Loads the user from the token subject.
4. Verifies either the TOTP code or recovery code.
5. Issues real access and refresh cookies.

### `POST /mfa/recovery-codes`

Regenerates all recovery codes.

Authentication:

```text
Requires full login session.
Requires password plus current MFA factor.
```

Body:

```json
{
  "password": "YourPassword1",
  "code": "123456"
}
```

Alternative body:

```json
{
  "password": "YourPassword1",
  "recovery_code": "abcd-1234-ef56-7890"
}
```

Purpose:

1. Confirms password.
2. Confirms MFA is enabled.
3. Verifies current MFA factor.
4. Deletes old recovery codes.
5. Generates and returns a new set.

### `POST /mfa/disable`

Disables MFA for the current account.

Authentication:

```text
Requires full login session.
Requires password plus current MFA factor.
```

Body:

```json
{
  "password": "YourPassword1",
  "code": "123456"
}
```

Purpose:

1. Confirms password.
2. Confirms MFA is currently enabled.
3. Verifies current MFA factor.
4. Deletes all recovery codes.
5. Clears the TOTP secret.
6. Sets `mfa_enabled` to false.
7. Clears replay and lockout state.

## Workflow: First-Time MFA Setup

```text
User is logged in
      |
      v
POST /api/v1/auth/mfa/setup
      |
      v
Backend checks password
      |
      v
Backend generates TOTP secret
      |
      v
Backend encrypts secret into users.totp_secret
      |
      v
Frontend shows QR/manual key from otpauth_url
      |
      v
User scans QR in authenticator app
      |
      v
POST /api/v1/auth/mfa/enable with first 6-digit code
      |
      v
Backend verifies code
      |
      v
Backend enables MFA and returns recovery codes
```

## Workflow: MFA Login

```text
POST /api/v1/auth/login
      |
      v
Backend verifies email/password
      |
      v
If mfa_enabled is false:
      issue normal auth cookies
      |
      v
If mfa_enabled is true:
      return challenge_token only
      |
      v
POST /api/v1/auth/mfa/verify
      |
      v
Backend verifies TOTP or recovery code
      |
      v
Backend issues auth cookies
```

## Workflow: Recovery Code Login

```text
POST /api/v1/auth/login
      |
      v
Receive challenge_token
      |
      v
POST /api/v1/auth/mfa/verify with recovery_code
      |
      v
Backend normalizes code
      |
      v
Backend compares against unused hashed recovery codes
      |
      v
If matched:
      set used_at
      issue auth cookies
```

## Function Documentation: `app/core/mfa.py`

This file contains low-level MFA helpers. It does not know about FastAPI routes or database sessions.

### Constants

```python
TOTP_INTERVAL_SECONDS = 30
TOTP_VALID_WINDOW = 1
RECOVERY_CODE_COUNT = 10
```

`TOTP_INTERVAL_SECONDS` means each authenticator code is based on a 30-second time window.

`TOTP_VALID_WINDOW = 1` means the backend accepts one previous, current, or one next TOTP window. This gives a small tolerance for clock drift.

`RECOVERY_CODE_COUNT = 10` means every regeneration creates ten recovery codes.

### `generate_totp_secret()`

```python
def generate_totp_secret() -> str:
    return pyotp.random_base32()
```

Purpose:

Generates a random Base32 secret compatible with authenticator apps.

Line-by-line:

1. Calls `pyotp.random_base32()`.
2. Returns a new TOTP seed that can be scanned or manually entered into an authenticator app.

### `encrypt_totp_secret(secret)`

```python
def encrypt_totp_secret(secret: str) -> str:
    return _fernet().encrypt(secret.encode("utf-8")).decode("utf-8")
```

Purpose:

Encrypts the TOTP secret before storing it in the database.

Line-by-line:

1. Calls `_fernet()` to get a Fernet encryption object.
2. Encodes the secret from string to bytes.
3. Encrypts the bytes.
4. Decodes the encrypted bytes back to a string for database storage.

### `decrypt_totp_secret(secret)`

```python
def decrypt_totp_secret(secret: str) -> str:
    try:
        return _fernet().decrypt(secret.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        return secret
```

Purpose:

Decrypts a stored TOTP secret before verifying an authenticator code.

Line-by-line:

1. Attempts to decrypt the stored string using Fernet.
2. Converts the input string to bytes.
3. Decrypts it.
4. Converts the decrypted bytes back to a string.
5. If decryption fails, returns the original value for backward compatibility with any older plaintext secrets.

Security note:

The fallback is convenient for migration, but once all old plaintext secrets are gone, you may later remove this fallback for stricter behavior.

### `build_otpauth_url(email, secret)`

```python
def build_otpauth_url(email: str, secret: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(
        name=email,
        issuer_name=settings.MFA_ISSUER_NAME,
    )
```

Purpose:

Builds the `otpauth://` URL used by authenticator apps and QR codes.

Line-by-line:

1. Creates a `pyotp.TOTP` object from the secret.
2. Calls `provisioning_uri`.
3. Uses the user's email as the account label.
4. Uses `MFA_ISSUER_NAME` as the app/service label.
5. Returns a URL that the frontend can encode as a QR code.

### `verify_totp_code(secret, code, last_used_counter=None)`

Purpose:

Validates a 6-digit TOTP code and returns the matching time-step counter. Returns `None` if invalid.

Line-by-line:

1. Removes whitespace from the submitted code.
2. Rejects the code if it is not exactly six digits.
3. Creates a `pyotp.TOTP` verifier using the secret and 30-second interval.
4. Calculates the current TOTP counter from Unix time.
5. Loops over the accepted window: previous, current, next.
6. Skips any counter that is less than or equal to `last_used_counter`.
7. Generates the expected code for that counter.
8. Compares submitted and expected code using `hmac.compare_digest`.
9. Returns the accepted counter if matched.
10. Returns `None` if no valid match was found.

Security purpose:

`last_used_counter` blocks replay. If a code was already accepted for a time window, the same or older TOTP window cannot be used again.

### `generate_recovery_codes()`

```python
def generate_recovery_codes() -> list[str]:
    return [_format_recovery_code(secrets.token_hex(8)) for _ in range(RECOVERY_CODE_COUNT)]
```

Purpose:

Generates one-time recovery codes.

Line-by-line:

1. Loops `RECOVERY_CODE_COUNT` times.
2. Generates 8 random bytes encoded as 16 hex characters.
3. Formats each code into readable chunks.
4. Returns the list of plain codes.

Storage note:

The plain codes are returned to the user once. The service stores only Argon2 hashes.

### `normalize_recovery_code(code)`

```python
def normalize_recovery_code(code: str) -> str:
    return code.replace("-", "").replace(" ", "").strip().lower()
```

Purpose:

Makes recovery-code input tolerant of dashes, spaces, and case.

Line-by-line:

1. Removes dashes.
2. Removes spaces.
3. Trims leading/trailing whitespace.
4. Converts to lowercase.

### `_format_recovery_code(code)`

```python
def _format_recovery_code(code: str) -> str:
    return "-".join(code[i : i + 4] for i in range(0, len(code), 4))
```

Purpose:

Formats a raw code into chunks such as:

```text
abcd-1234-ef56-7890
```

Line-by-line:

1. Slices the raw code into groups of four characters.
2. Joins those groups with dashes.
3. Returns the readable recovery code.

### `_fernet()`

```python
def _fernet() -> Fernet:
    key_source = settings.MFA_ENCRYPTION_KEY or settings.JWT_SECRET
    digest = hashlib.sha256(key_source.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))
```

Purpose:

Creates a Fernet encryption object from application secrets.

Line-by-line:

1. Uses `MFA_ENCRYPTION_KEY` if configured.
2. Falls back to `JWT_SECRET` if no dedicated MFA key is configured.
3. Hashes the selected secret with SHA-256 to produce 32 bytes.
4. Base64-url encodes the digest because Fernet requires a URL-safe Base64 key.
5. Returns a Fernet object used for encryption/decryption.

## Function Documentation: `app/services/mfa_service.py`

This file contains the main MFA business logic. It connects helpers, database models, password verification, and token issuance.

### `get_mfa_status(user, db)`

Purpose:

Returns whether MFA is enabled and how many unused recovery codes remain.

Line-by-line:

1. Queries `MFARecoveryCode`.
2. Filters to the current user's codes.
3. Filters to codes where `used_at` is `None`.
4. Counts the unused codes.
5. Returns `enabled` from `user.mfa_enabled`.
6. Returns `recovery_codes_remaining` only if MFA is enabled; otherwise returns `0`.

### `start_mfa_setup(password, user, db)`

Purpose:

Begins MFA setup for a logged-in user.

Line-by-line:

1. Calls `_require_password` to confirm the user's password.
2. Rejects the request if MFA is already enabled.
3. Calls `generate_totp_secret`.
4. Encrypts the secret with `encrypt_totp_secret`.
5. Stores the encrypted secret in `user.totp_secret`.
6. Clears replay counter state.
7. Clears failed attempt count.
8. Clears lockout state.
9. Commits the database changes.
10. Returns the raw secret, `otpauth_url`, and issuer name.

Why password is required:

This prevents someone who temporarily gets access to an unlocked browser session from silently enrolling their own authenticator app without knowing the password.

### `enable_mfa(password, code, user, db)`

Purpose:

Finishes MFA setup by verifying the first authenticator code.

Line-by-line:

1. Verifies password.
2. Rejects if MFA is already enabled.
3. Rejects if no setup secret exists.
4. Decrypts the stored TOTP secret.
5. Verifies the submitted TOTP code.
6. Rejects invalid code.
7. Generates replacement recovery codes.
8. Sets `mfa_enabled` to true.
9. Stores the accepted TOTP counter to block immediate replay.
10. Resets failure and lockout state.
11. Commits changes.
12. Returns success message and recovery codes.

Important:

Recovery codes are only returned in this response. The database stores only hashes.

### `verify_mfa_challenge(challenge_token, code, recovery_code, db, response)`

Purpose:

Completes login after the password step for an MFA-enabled user.

Line-by-line:

1. Decodes the challenge token as an access token.
2. Confirms the token has `scope` equal to `mfa_challenge` or legacy `totp_challenge`.
3. Rejects any token with the wrong scope.
4. Loads the user from token payload via `_get_user_from_payload`.
5. Confirms MFA is enabled for that user.
6. Calls `_verify_mfa_factor`.
7. Issues normal access and refresh cookies with `_issue_tokens`.
8. Returns a success message.
9. If a recovery code was used, includes the number of remaining recovery codes in the message.

Security purpose:

The password login step alone is not enough for MFA-enabled users. Full auth cookies are issued only after this function succeeds.

### `disable_mfa(password, code, recovery_code, user, db)`

Purpose:

Disables MFA for the current account.

Line-by-line:

1. Verifies password.
2. Confirms MFA is currently enabled.
3. Verifies either TOTP code or recovery code.
4. Deletes all recovery codes for the user.
5. Clears `totp_secret`.
6. Sets `mfa_enabled` to false.
7. Clears last-used TOTP counter.
8. Clears failure count.
9. Clears lockout timestamp.
10. Commits changes.
11. Returns success message.

Why require password plus MFA:

Disabling MFA is a sensitive account-security action, so it requires both knowledge of the password and possession of a current second factor.

### `regenerate_recovery_codes(password, code, recovery_code, user, db)`

Purpose:

Replaces all old recovery codes with a new set.

Line-by-line:

1. Verifies password.
2. Confirms MFA is enabled.
3. Verifies current MFA factor.
4. Calls `_replace_recovery_codes`.
5. Commits changes.
6. Returns success message and new recovery codes.

Security behavior:

Old recovery codes are deleted before new codes are stored, so only the newest set can work.

### `_verify_mfa_factor(user, db, code, recovery_code)`

Purpose:

Shared validator for TOTP and recovery-code checks.

Return value:

```text
False = TOTP code was used
True  = recovery code was used
```

Line-by-line:

1. Rejects the request if both `code` and `recovery_code` are provided.
2. Rejects the request if neither is provided.
3. Calls `_enforce_mfa_lock`.
4. If a TOTP code was provided, decrypts the secret.
5. Verifies the TOTP code with replay protection.
6. If valid, stores the accepted counter.
7. Resets MFA failures.
8. Commits changes.
9. Returns `False` to mean TOTP was used.
10. If a recovery code was provided, calls `_consume_recovery_code`.
11. If valid, resets MFA failures.
12. Commits changes.
13. Returns `True` to mean recovery code was used.
14. If neither factor is valid, records a failure.
15. Raises `401 Invalid MFA code`.

### `_consume_recovery_code(user, db, recovery_code)`

Purpose:

Checks a submitted recovery code against unused stored recovery-code hashes.

Line-by-line:

1. Normalizes the submitted recovery code.
2. Rejects it if the normalized code is not 16 characters.
3. Queries unused recovery codes for the user.
4. Loops through stored code hashes.
5. Uses `verify_password` to compare the submitted code with each Argon2 hash.
6. If matched, sets `used_at` to current UTC time.
7. Returns `True`.
8. Returns `False` if no match was found.

Why loop through hashes:

Argon2 hashes are salted, so the backend cannot directly query by hash. It must verify the submitted code against each unused hash.

### `_replace_recovery_codes(user, db)`

Purpose:

Deletes old recovery codes and creates a fresh set.

Line-by-line:

1. Deletes all existing recovery codes for the user.
2. Generates new plain recovery codes.
3. Loops over each plain code.
4. Normalizes the code.
5. Hashes the normalized code with Argon2.
6. Adds a new `MFARecoveryCode` row to the database.
7. Returns the plain codes so they can be shown to the user once.

### `_record_mfa_failure(user, db)`

Purpose:

Tracks failed MFA attempts and applies lockout if the user fails too many times.

Line-by-line:

1. Increments `mfa_failed_attempts`.
2. If failures reach `MFA_MAX_FAILED_ATTEMPTS`, sets `mfa_locked_until`.
3. Lock expiry is current UTC time plus `MFA_LOCK_MINUTES`.
4. Commits changes.

### `_reset_mfa_failures(user)`

Purpose:

Clears MFA failure and lockout state after successful MFA verification or expired lockout.

Line-by-line:

1. Sets `mfa_failed_attempts` to `0`.
2. Sets `mfa_locked_until` to `None`.

### `_enforce_mfa_lock(user)`

Purpose:

Blocks MFA verification during a temporary lockout window.

Line-by-line:

1. Reads `mfa_locked_until`.
2. If the datetime is naive, treats it as UTC.
3. Gets the current UTC time.
4. If lockout is still active, raises `429 Too Many Requests`.
5. If lockout has expired, resets failure state.

### `_require_password(user, password)`

Purpose:

Confirms the user knows their current password before sensitive MFA operations.

Line-by-line:

1. Calls `verify_password`.
2. If password verification fails, raises `401 Invalid credentials`.
3. Returns nothing if valid.

### `_require_mfa_enabled(user)`

Purpose:

Ensures MFA operations only proceed for accounts that actually have MFA enabled.

Line-by-line:

1. Checks `user.mfa_enabled`.
2. Checks `user.totp_secret`.
3. If either is missing, raises `400 MFA is not enabled`.

### `_get_user_from_payload(payload, db)`

Purpose:

Loads the user referenced by a challenge token.

Line-by-line:

1. Reads `sub` from the JWT payload.
2. Rejects the token if `sub` is missing.
3. Queries the user by ID.
4. Rejects if user does not exist.
5. Returns the `User` model.

## Function Documentation: `app/services/auth_service.py` MFA Changes

### `login_user(email, password, db, response)`

Existing purpose:

Verifies email/password and either logs the user in or rejects invalid credentials.

MFA-specific behavior:

1. Looks up user by email.
2. Uses a dummy Argon2 hash if user does not exist to reduce email enumeration timing leaks.
3. Verifies password.
4. If password is invalid, raises `401`.
5. If `user.mfa_enabled` and `user.totp_secret` are present, creates a short-lived access token with:

```python
{"sub": str(user.id), "scope": "mfa_challenge"}
```

6. Uses `MFA_CHALLENGE_EXPIRE_MINUTES` for challenge token expiry.
7. Returns:

```json
{
  "requires_2fa": true,
  "requires_mfa": true,
  "challenge_token": "...",
  "expires_in": 300
}
```

8. If MFA is not enabled, issues auth cookies as before.

Why `requires_2fa` and `requires_mfa` both exist:

`requires_mfa` is the clearer new name. `requires_2fa` is kept for backward compatibility with any frontend code that already checks that field.

## Function Documentation: `app/core/jwt.py` MFA Change

### `create_access_token(data, expires_delta=None)`

Purpose:

Creates a signed JWT access token.

MFA-specific change:

The function now accepts `expires_delta`.

Line-by-line:

1. Copies the provided payload.
2. Uses custom `expires_delta` if provided.
3. Otherwise uses the normal `ACCESS_TOKEN_EXPIRE_MINUTES`.
4. Adds `exp`.
5. Adds `type = "access"`.
6. Signs token with `JWT_SECRET`.

Why this matters:

Normal access tokens and MFA challenge tokens should not have the same lifespan. Challenge tokens are intentionally shorter.

## Function Documentation: `app/core/deps.py` MFA Change

### `get_current_user(...)`

Existing purpose:

Reads the `access_token` cookie and returns the authenticated user.

MFA-specific behavior:

```python
if payload.get("scope") in {"totp_challenge", "mfa_challenge"}:
    raise HTTPException(...)
```

Purpose:

Prevents a challenge token from being used as a real login token.

Without this check, a user who only completed the password step could potentially access authenticated routes before completing MFA.

## Function Documentation: `app/api/routes/auth.py`

This file exposes the MFA service through HTTP endpoints.

### `mfa_status(...)`

Route:

```text
GET /api/v1/auth/mfa/status
```

Line-by-line:

1. Gets database session from `get_db`.
2. Gets authenticated user from `get_current_user`.
3. Calls `mfa_service.get_mfa_status`.
4. Returns `MFAStatusResponse`.

### `setup_mfa(...)`

Route:

```text
POST /api/v1/auth/mfa/setup
```

Line-by-line:

1. Receives `MFASetupRequest`.
2. Gets database session.
3. Gets authenticated user.
4. Calls `mfa_service.start_mfa_setup`.
5. Returns `MFASetupResponse`.

### `enable_mfa(...)`

Route:

```text
POST /api/v1/auth/mfa/enable
```

Line-by-line:

1. Receives password and TOTP code.
2. Gets database session.
3. Gets authenticated user.
4. Calls `mfa_service.enable_mfa`.
5. Returns recovery codes.

### `verify_mfa(...)`

Route:

```text
POST /api/v1/auth/mfa/verify
```

Line-by-line:

1. Receives challenge token and one MFA factor.
2. Gets database session.
3. Does not require `get_current_user`, because user is not fully logged in yet.
4. Calls `mfa_service.verify_mfa_challenge`.
5. On success, response cookies are set.

### `regenerate_recovery_codes(...)`

Route:

```text
POST /api/v1/auth/mfa/recovery-codes
```

Line-by-line:

1. Receives password and one MFA factor.
2. Gets database session.
3. Gets authenticated user.
4. Calls `mfa_service.regenerate_recovery_codes`.
5. Returns new recovery codes.

### `disable_mfa(...)`

Route:

```text
POST /api/v1/auth/mfa/disable
```

Line-by-line:

1. Receives password and one MFA factor.
2. Gets database session.
3. Gets authenticated user.
4. Calls `mfa_service.disable_mfa`.
5. Returns success message.

## Schema Documentation: `app/schemas/auth.py`

### `MFASetupRequest`

Fields:

| Field | Purpose |
| --- | --- |
| `password` | Confirms the user before beginning setup. |

### `MFASetupResponse`

Fields:

| Field | Purpose |
| --- | --- |
| `secret` | Manual setup key for authenticator apps. |
| `otpauth_url` | QR-code payload for authenticator apps. |
| `issuer` | App name shown in authenticator app. |

### `MFAEnableRequest`

Fields:

| Field | Purpose |
| --- | --- |
| `password` | Confirms the user before enabling MFA. |
| `code` | First TOTP code from authenticator app. |

### `MFARecoveryCodesResponse`

Fields:

| Field | Purpose |
| --- | --- |
| `message` | Human-readable result. |
| `recovery_codes` | Plain recovery codes shown once. |

### `MFAVerifyRequest`

Fields:

| Field | Purpose |
| --- | --- |
| `challenge_token` | Temporary token returned by login. |
| `code` | TOTP code, optional. |
| `recovery_code` | Recovery code, optional. |

Validator:

The `model_validator` enforces exactly one MFA factor:

```text
Either code or recovery_code, never both, never neither.
```

### `MFADisableRequest`

Fields:

| Field | Purpose |
| --- | --- |
| `password` | Confirms account ownership. |
| `code` | TOTP code, optional. |
| `recovery_code` | Recovery code, optional. |

This schema is also reused for recovery-code regeneration because both operations require the same proof: password plus current MFA factor.

### `MFAStatusResponse`

Fields:

| Field | Purpose |
| --- | --- |
| `enabled` | Whether MFA is enabled. |
| `recovery_codes_remaining` | Count of unused recovery codes. |

## Migration Documentation

Migration file:

```text
migrations/versions/5b1f2c3d4e5a_add_mfa_support.py
```

### `upgrade()`

Purpose:

Applies MFA schema changes.

Line-by-line:

1. Adds `users.mfa_enabled`.
2. Uses a temporary server default of `false` so existing users get a valid value.
3. Adds `users.mfa_last_used_counter`.
4. Adds `users.mfa_failed_attempts`.
5. Uses a temporary server default of `0` so existing users get a valid value.
6. Adds `users.mfa_locked_until`.
7. Removes server default from `mfa_enabled`.
8. Removes server default from `mfa_failed_attempts`.
9. Creates `mfa_recovery_codes`.
10. Adds foreign key from recovery codes to users.
11. Creates index on recovery-code `id`.
12. Creates index on recovery-code `user_id`.

### `downgrade()`

Purpose:

Reverses MFA schema changes.

Line-by-line:

1. Drops recovery-code indexes.
2. Drops `mfa_recovery_codes`.
3. Drops `users.mfa_locked_until`.
4. Drops `users.mfa_failed_attempts`.
5. Drops `users.mfa_last_used_counter`.
6. Drops `users.mfa_enabled`.

Warning:

Downgrading removes MFA recovery-code data and MFA state.

## Security Properties

### Password Required For Sensitive MFA Changes

The following operations require password confirmation:

1. Setup MFA.
2. Enable MFA.
3. Disable MFA.
4. Regenerate recovery codes.

This protects against someone using an already-open browser session to silently change account security settings.

### TOTP Secret Encryption

TOTP secrets are encrypted before storage. This reduces damage if the database is leaked.

The encryption key comes from:

1. `MFA_ENCRYPTION_KEY`, if set.
2. `JWT_SECRET`, as fallback.

### Recovery Codes Are Hashed

Recovery codes are not encrypted; they are hashed using the existing password hashing helpers.

This means:

1. The backend can verify a submitted recovery code.
2. The backend cannot display old recovery codes again.
3. A database leak does not directly expose recovery codes.

### TOTP Replay Protection

The backend stores `mfa_last_used_counter`.

If a TOTP code was already accepted for a time window, the same counter or older counters are rejected.

This protects against immediate reuse of a valid 6-digit code.

### Temporary Lockout

Invalid MFA attempts increment `mfa_failed_attempts`.

After `MFA_MAX_FAILED_ATTEMPTS`, the account's MFA verification is locked until `mfa_locked_until`.

This slows brute-force attempts against 6-digit TOTP codes.

### Challenge Token Scope

Challenge tokens include:

```json
{
  "scope": "mfa_challenge"
}
```

`get_current_user` rejects this scope. This ensures challenge tokens cannot access normal authenticated routes.

## Frontend Integration Notes

### Setup Screen

Frontend should:

1. Call `/mfa/setup`.
2. Render QR code from `otpauth_url`.
3. Also show the manual `secret`.
4. Ask user for the current 6-digit code.
5. Call `/mfa/enable`.
6. Display recovery codes once.

### Login Screen

Frontend should:

1. Call `/login`.
2. If response has `requires_mfa: true`, show MFA verification UI.
3. Store `challenge_token` temporarily in memory.
4. Call `/mfa/verify`.
5. After success, continue normal logged-in flow.

Do not store `challenge_token` in localStorage. It is short-lived and should only live during the login attempt.

### Recovery Codes UI

Frontend should:

1. Clearly tell users recovery codes are shown once.
2. Offer copy/download/print controls.
3. Show remaining recovery-code count from `/mfa/status`.
4. Allow regeneration from account security settings.

## Manual Testing Checklist

### Setup And Enable

1. Log in normally.
2. Call `POST /api/v1/auth/mfa/setup`.
3. Add the returned secret to an authenticator app.
4. Call `POST /api/v1/auth/mfa/enable` with the current 6-digit code.
5. Confirm recovery codes are returned.
6. Call `GET /api/v1/auth/mfa/status`.
7. Confirm `enabled` is `true`.

### MFA Login

1. Log out.
2. Call `POST /api/v1/auth/login`.
3. Confirm response includes `requires_mfa: true`.
4. Call `POST /api/v1/auth/mfa/verify` with challenge token and TOTP code.
5. Confirm auth cookies are set.
6. Call `/api/v1/users/me`.
7. Confirm authenticated access works.

### Recovery Code

1. Log in with password.
2. Use one recovery code at `/mfa/verify`.
3. Confirm login succeeds.
4. Try the same recovery code again.
5. Confirm it fails.

### Replay Protection

1. Submit a valid TOTP code.
2. Try to submit the same code again in the same 30-second window.
3. Confirm it fails.

### Lockout

1. Submit wrong MFA codes repeatedly.
2. After configured max attempts, confirm response is `429`.
3. Wait until lock expires.
4. Submit a valid code.
5. Confirm login works again.

## Deployment Notes

### Render Environment Variables

Recommended:

```env
MFA_ISSUER_NAME=CodeFolio
MFA_CHALLENGE_EXPIRE_MINUTES=5
MFA_MAX_FAILED_ATTEMPTS=5
MFA_LOCK_MINUTES=5
MFA_ENCRYPTION_KEY=long-random-production-secret
```

Required already:

```env
DATABASE_URL=...
JWT_SECRET=...
JWT_ALGORITHM=...
ACCESS_TOKEN_EXPIRE_MINUTES=...
FRONTEND_URL=...
BACKEND_URL=...
DEBUG=False
```

### Migration

Run:

```bash
alembic upgrade head
```

If a database has a stale Alembic revision pointer, repair it first:

```bash
alembic stamp --purge 9c1585331b3f
alembic upgrade head
```

Use the repair command only when the existing schema already matches the init migration.

## Future Improvements

Useful future upgrades:

1. Add email notification when MFA is enabled, disabled, or recovery codes are regenerated.
2. Add audit-log table for security events.
3. Add frontend QR code rendering.
4. Add WebAuthn/passkeys as a stronger MFA option.
5. Add admin support flow for users who lose all factors.
6. Add automated tests for setup, login challenge, recovery-code use, lockout, and replay protection.

