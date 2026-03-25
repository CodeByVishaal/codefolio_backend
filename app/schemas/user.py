from __future__ import annotations
from pydantic import BaseModel, EmailStr
from datetime import datetime
from typing import Optional
from app.models.project import ProjectStatus


# ── Nested shapes used inside profile responses ───────────────────────────────


class PublicProjectSummary(BaseModel):
    """
    A project as it appears on the public portfolio page.
    Omits user_id, is_public flag, and internal timestamps — only
    the fields a recruiter or visitor actually cares about.
    """

    id: int
    title: str
    description: Optional[str]
    status: ProjectStatus
    tech_stack: list[str]
    github_url: Optional[str]
    live_url: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class PublicJournalSummary(BaseModel):
    """
    A journal entry as it appears on the public portfolio page.
    Omits user_id — never expose internal IDs in public responses.
    body is included so visitors can read the full entry from the profile.
    """

    id: int
    title: str
    body: str
    tags: list[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class PublicStats(BaseModel):
    """
    Aggregate numbers shown on the public profile.
    These are summary counts — no individual session or task details exposed.
    """

    total_projects: int
    total_public_projects: int
    total_sessions: int
    total_hours: float
    total_tasks_completed: int


# ── Private profile (/users/me) ───────────────────────────────────────────────


class MeResponse(BaseModel):
    """
    Full private profile for the authenticated user.
    Includes email, role, verification status, and all stats.
    Never returned to unauthenticated callers.
    """

    id: int
    name: str
    email: EmailStr
    role: str
    is_verified: bool
    created_at: datetime
    # Aggregate stats computed by the service
    total_projects: int
    total_sessions: int
    total_hours: float
    total_tasks_completed: int

    model_config = {"from_attributes": True}


# ── Public profile (/users/{id}/profile) ─────────────────────────────────────


class PublicProfileResponse(BaseModel):
    """
    Public portfolio page — no auth required to view.

    Deliberately excludes:
    - email         (private contact info)
    - role          (internal system detail)
    - is_verified   (internal system detail)
    - Private projects (is_public=False)
    - Private journal entries (is_public=False)

    Only aggregate stats are shown, not individual session or task details.
    """

    id: int
    name: str
    member_since: datetime
    stats: PublicStats
    projects: list[PublicProjectSummary]
    journal: list[PublicJournalSummary]
