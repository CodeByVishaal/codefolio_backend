from sqlalchemy.orm import Session
from sqlalchemy import func
from fastapi import HTTPException, status

from app.models.users import User
from app.models.project import Project
from app.models.task import Task, TaskStatus
from app.models.session import CodingSession
from app.models.journal import JournalEntry
from app.schemas.user import MeResponse, PublicProfileResponse, PublicStats


# ── Private profile ───────────────────────────────────────────────────────────


def get_me(user: User, db: Session) -> MeResponse:
    """
    Return the full private profile for the currently authenticated user.
    Computes stats with SQL aggregations — no Python loops over rows.
    """
    # Total projects owned by this user
    total_projects = (
        db.query(func.count(Project.id)).filter(Project.user_id == user.id).scalar()
        or 0
    )

    # Total coding sessions
    total_sessions = (
        db.query(func.count(CodingSession.id))
        .filter(CodingSession.user_id == user.id)
        .scalar()
        or 0
    )

    # Total minutes coded — converted to hours at the response boundary
    total_mins = (
        db.query(func.sum(CodingSession.duration_mins))
        .filter(CodingSession.user_id == user.id)
        .scalar()
        or 0
    )

    # Tasks completed — reach tasks through projects owned by this user
    total_tasks_completed = (
        db.query(func.count(Task.id))
        .join(Project, Task.project_id == Project.id)
        .filter(
            Project.user_id == user.id,
            Task.status == TaskStatus.done,
        )
        .scalar()
        or 0
    )

    return MeResponse(
        id=user.id,
        name=user.name,
        email=user.email,
        role=user.role.value,  # .value converts enum to string: "developer"
        is_verified=user.is_verified,
        created_at=user.created_at,
        total_projects=total_projects,
        total_sessions=total_sessions,
        total_hours=round(total_mins / 60, 1),
        total_tasks_completed=total_tasks_completed,
    )


# ── Public profile ────────────────────────────────────────────────────────────


def get_public_profile(user_id: int, db: Session) -> PublicProfileResponse:
    """
    Return the public-facing portfolio for any user by ID.
    Requires no authentication — this endpoint is publicly accessible.

    Only returns:
    - Basic identity (name, join date)
    - Public projects (is_public=True)
    - Public journal entries (is_public=True)
    - Aggregate stats (counts and totals — no individual records)
    """
    # ── 1. Confirm the user exists ────────────────────────────────────────────
    user = db.query(User).filter(User.id == user_id).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User {user_id} not found",
        )

    # ── 2. Public projects only ───────────────────────────────────────────────
    public_projects = (
        db.query(Project)
        .filter(
            Project.user_id == user_id,
            Project.is_public == True,  # noqa: E712 — SQLAlchemy requires == not 'is'
        )
        .order_by(Project.updated_at.desc())
        .all()
    )

    # ── 3. Public journal entries only ────────────────────────────────────────
    public_journal = (
        db.query(JournalEntry)
        .filter(
            JournalEntry.user_id == user_id,
            JournalEntry.is_public == True,  # noqa: E712
        )
        .order_by(JournalEntry.updated_at.desc())
        .all()
    )

    # ── 4. Aggregate stats ────────────────────────────────────────────────────
    total_projects = (
        db.query(func.count(Project.id)).filter(Project.user_id == user_id).scalar()
        or 0
    )

    total_public_projects = len(public_projects)  # already fetched above

    total_sessions = (
        db.query(func.count(CodingSession.id))
        .filter(CodingSession.user_id == user_id)
        .scalar()
        or 0
    )

    total_mins = (
        db.query(func.sum(CodingSession.duration_mins))
        .filter(CodingSession.user_id == user_id)
        .scalar()
        or 0
    )

    total_tasks_completed = (
        db.query(func.count(Task.id))
        .join(Project, Task.project_id == Project.id)
        .filter(
            Project.user_id == user_id,
            Task.status == TaskStatus.done,
        )
        .scalar()
        or 0
    )

    # ── 5. Assemble and return ────────────────────────────────────────────────
    return PublicProfileResponse(
        id=user.id,
        name=user.name,
        member_since=user.created_at,
        stats=PublicStats(
            total_projects=total_projects,
            total_public_projects=total_public_projects,
            total_sessions=total_sessions,
            total_hours=round(total_mins / 60, 1),
            total_tasks_completed=total_tasks_completed,
        ),
        projects=public_projects,
        journal=public_journal,
    )
