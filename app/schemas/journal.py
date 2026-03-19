from pydantic import BaseModel, field_validator
from datetime import datetime
from typing import Optional


class JournalCreate(BaseModel):
    title: str
    body: str
    tags: list[str] = []
    is_public: bool = False

    @field_validator("title")
    @classmethod
    def title_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Title cannot be blank")
        return v.strip()

    @field_validator("body")
    @classmethod
    def body_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Body cannot be blank")
        return v.strip()

    @field_validator("tags")
    @classmethod
    def clean_tags(cls, v: list[str]) -> list[str]:
        # Lowercase, strip whitespace, deduplicate
        return list(dict.fromkeys(tag.strip().lower() for tag in v if tag.strip()))


class JournalUpdate(BaseModel):
    title: Optional[str] = None
    body: Optional[str] = None
    tags: Optional[list[str]] = None
    is_public: Optional[bool] = None


class JournalResponse(BaseModel):
    id: int
    user_id: int
    title: str
    body: str
    tags: list[str]
    is_public: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class JournalPublicResponse(BaseModel):
    """Stripped response for public portfolio — no user_id exposed."""

    id: int
    title: str
    body: str
    tags: list[str]
    created_at: datetime

    model_config = {"from_attributes": True}
