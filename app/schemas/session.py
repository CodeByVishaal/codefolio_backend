from pydantic import BaseModel, field_validator
from datetime import datetime, date
from typing import Optional


class SessionCreate(BaseModel):
    duration_mins: int
    session_date: date
    project_id: Optional[int] = None
    notes: Optional[str] = None

    @field_validator("duration_mins")
    @classmethod
    def duration_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("Duration must be greater than zero")
        if v > 1440:
            raise ValueError("Duration cannot exceed 1440 minutes (24 hours)")
        return v


class SessionUpdate(BaseModel):
    duration_mins: Optional[int] = None
    session_date: Optional[date] = None
    project_id: Optional[int] = None
    notes: Optional[str] = None


class SessionResponse(BaseModel):
    id: int
    user_id: int
    project_id: Optional[int]
    duration_mins: int
    session_date: date
    notes: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}
