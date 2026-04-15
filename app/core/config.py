from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str
    JWT_SECRET: str
    JWT_ALGORITHM: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int
    DEBUG: bool = False
    FRONTEND_URL: str = "http://localhost:5173"  # Dev default

    class Config:
        env_file = ".env"


settings = Settings()
