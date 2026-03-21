from pydantic import BaseModel, field_validator
from datetime import datetime
from typing import Optional
from app.models.project import ProjectStatus


class ProjectCreate(BaseModel):
    title: str
    description: Optional[str] = None
    status: ProjectStatus = ProjectStatus.planning
    tech_stack: list[str] = []
    github_url: Optional[str] = None
    live_url: Optional[str] = None
    is_public: bool = False

    @field_validator("title")
    @classmethod
    def title_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Title cannot be blank")
        return v.strip()

    @field_validator("tech_stack")
    @classmethod
    def clean_tech_stack(cls, v: list[str]) -> list[str]:
        # Strip whitespace from each tag, remove blanks, deduplicate
        cleaned = list(dict.fromkeys(tag.strip().lower() for tag in v if tag.strip()))
        return cleaned


class ProjectUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[ProjectStatus] = None
    tech_stack: Optional[list[str]] = None
    github_url: Optional[str] = None
    live_url: Optional[str] = None
    is_public: Optional[bool] = None


class ProjectResponse(BaseModel):
    id: int
    user_id: int
    title: str
    description: Optional[str]
    status: ProjectStatus
    tech_stack: list[str]
    github_url: Optional[str]
    live_url: Optional[str]
    is_public: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProjectWithTasksResponse(ProjectResponse):
    """Used on single-project GET — includes full task list."""

    tasks: list["TaskResponse"] = []

    model_config = {"from_attributes": True}


# Import at the end to avoid circular imports, then rebuild the model
from app.schemas.task import TaskResponse  # noqa: E402, F401

ProjectWithTasksResponse.model_rebuild()
