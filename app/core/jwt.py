from datetime import datetime, timedelta, timezone
from jose import jwt
from app.core.config import settings


def create_access_token(data: dict):
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    # data.update({"exp": expire})
    # return jwt.encode(data, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

    payload = data.copy()
    payload.update({"exp": expire})

    token = jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    return token
