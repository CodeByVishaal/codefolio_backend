from sqlalchemy import Column, Integer, String, DateTime, Enum as SAEnum, Boolean
from datetime import datetime, timezone
from app.db.base import Base
import enum


class UserRole(enum.Enum):
    admin = "admin"
    developer = "developer"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(SAEnum(UserRole), nullable=False, default=UserRole.developer)
    is_verified = Column(Boolean, nullable=False, default=False)
    totp_secret = Column(String, nullable=True, default=None)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
