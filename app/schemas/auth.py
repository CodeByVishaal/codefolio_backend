from pydantic import BaseModel, EmailStr, field_validator, model_validator


class UserRegister(BaseModel):
    name: str
    email: EmailStr
    password: str

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        errors = []
        if len(v) < 8:
            errors.append("at least 8 characters")
        if not any(c.isupper() for c in v):
            errors.append("one uppercase letter")
        if not any(c.isdigit() for c in v):
            errors.append("one number")
        if errors:
            raise ValueError(f"Password must contain: {', '.join(errors)}")
        return v

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Name cannot be blank")
        return v.strip()


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class MFASetupRequest(BaseModel):
    password: str


class MFASetupResponse(BaseModel):
    secret: str
    otpauth_url: str
    issuer: str


class MFAEnableRequest(BaseModel):
    password: str
    code: str


class MFARecoveryCodesResponse(BaseModel):
    message: str
    recovery_codes: list[str]


class MFAVerifyRequest(BaseModel):
    challenge_token: str
    code: str | None = None
    recovery_code: str | None = None

    @model_validator(mode="after")
    def exactly_one_factor(self) -> "MFAVerifyRequest":
        if bool(self.code) == bool(self.recovery_code):
            raise ValueError("Provide either code or recovery_code")
        return self


class MFADisableRequest(BaseModel):
    password: str
    code: str | None = None
    recovery_code: str | None = None

    @model_validator(mode="after")
    def exactly_one_factor(self) -> "MFADisableRequest":
        if bool(self.code) == bool(self.recovery_code):
            raise ValueError("Provide either code or recovery_code")
        return self


class MFAStatusResponse(BaseModel):
    enabled: bool
    recovery_codes_remaining: int


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
