from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str
    JWT_SECRET: str
    JWT_ALGORITHM: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int
    DEBUG: bool = False
    FRONTEND_URL: str
    BACKEND_URL: str
    MFA_ISSUER_NAME: str = "CodeFolio"
    MFA_CHALLENGE_EXPIRE_MINUTES: int = 5
    MFA_MAX_FAILED_ATTEMPTS: int = 5
    MFA_LOCK_MINUTES: int = 5
    MFA_ENCRYPTION_KEY: str | None = None

    class Config:
        env_file = ".env"


settings = Settings()
