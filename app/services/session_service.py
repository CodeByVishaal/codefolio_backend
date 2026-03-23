from datetime import date
from sqlalchemy.orm import Session
from sqlalchemy import func
from fastapi import HTTPException, status

from app.models.session import CodingSession
from app.models.project import Project
from app.models.users import User
from app.schemas.session import SessionCreate, SessionUpdate


# ── Private helpers ──────────────────────────────────────────────────────────


def _get_session_or_404(session_id: int, user_id: int, db: Session) -> CodingSession:
    """
    Fetch a coding session by ID and verify it belongs to the requesting user.
    Same two-step pattern as Phase 3: existence check first, ownership second.
    """
    session = db.query(CodingSession).filter(CodingSession.id == session_id).first()

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found",
        )

    if session.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to access this session",
        )

    return session


def _validate_project_ownership(project_id: int, user_id: int, db: Session) -> None:
    """
    If a project_id is provided, confirm it exists AND belongs to this user.
    Called before creating or updating a session with a project link.
    Prevents a user from logging sessions against someone else's project.
    """
    project = db.query(Project).filter(Project.id == project_id).first()

    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found",
        )

    if project.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to link to this project",
        )


# ── Create ───────────────────────────────────────────────────────────────────


def create_session(data: SessionCreate, user: User, db: Session) -> CodingSession:
    # If a project is linked, verify ownership before creating
    if data.project_id is not None:
        _validate_project_ownership(data.project_id, user.id, db)

    coding_session = CodingSession(
        user_id=user.id,
        project_id=data.project_id,
        duration_mins=data.duration_mins,
        session_date=data.session_date,
        notes=data.notes,
    )
    db.add(coding_session)
    db.commit()
    db.refresh(coding_session)
    return coding_session


# ── List ─────────────────────────────────────────────────────────────────────


def list_sessions(
    user: User,
    db: Session,
    project_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[CodingSession]:
    """
    List sessions for the current user with optional filters.

    date_from / date_to filter on session_date (the Date column, not created_at).
    This lets the frontend build weekly/monthly views simply by passing
    the first and last day of the desired period.
    """
    query = db.query(CodingSession).filter(CodingSession.user_id == user.id)

    if project_id is not None:
        query = query.filter(CodingSession.project_id == project_id)

    if date_from is not None:
        query = query.filter(CodingSession.session_date >= date_from)

    if date_to is not None:
        query = query.filter(CodingSession.session_date <= date_to)

    # Most recent sessions first — natural order for a log/timeline view
    return query.order_by(CodingSession.session_date.desc()).all()


# ── Get one ──────────────────────────────────────────────────────────────────


def get_session(session_id: int, user: User, db: Session) -> CodingSession:
    return _get_session_or_404(session_id, user.id, db)


# ── Update ───────────────────────────────────────────────────────────────────


def update_session(
    session_id: int, data: SessionUpdate, user: User, db: Session
) -> CodingSession:
    coding_session = _get_session_or_404(session_id, user.id, db)

    update_data = data.model_dump(exclude_unset=True)

    # If the update changes the linked project, validate the new project too
    if "project_id" in update_data and update_data["project_id"] is not None:
        _validate_project_ownership(update_data["project_id"], user.id, db)

    for field, value in update_data.items():
        setattr(coding_session, field, value)

    db.commit()
    db.refresh(coding_session)
    return coding_session


# ── Delete ───────────────────────────────────────────────────────────────────


def delete_session(session_id: int, user: User, db: Session) -> dict:
    coding_session = _get_session_or_404(session_id, user.id, db)
    db.delete(coding_session)
    db.commit()
    return {"message": "Session deleted successfully"}


# ── Summary ──────────────────────────────────────────────────────────────────


def get_summary(
    user: User,
    db: Session,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict:
    """
    Aggregate total minutes coded for the given period.
    Returns total_mins, total_sessions, and a per-project breakdown.

    This is a lightweight preview of the full analytics layer (Phase 6).
    It runs pure SQL aggregations — no Python loops over rows.
    """
    query = db.query(CodingSession).filter(CodingSession.user_id == user.id)

    if date_from:
        query = query.filter(CodingSession.session_date >= date_from)
    if date_to:
        query = query.filter(CodingSession.session_date <= date_to)

    # SUM and COUNT in one query — no fetching all rows into Python
    totals = (
        db.query(
            func.sum(CodingSession.duration_mins).label("total_mins"),
            func.count(CodingSession.id).label("total_sessions"),
        )
        .filter(
            CodingSession.user_id == user.id,
            CodingSession.session_date >= date_from if date_from else True,
            CodingSession.session_date <= date_to if date_to else True,
        )
        .first()
    )

    # Per-project breakdown: how many minutes per project
    per_project = (
        db.query(
            CodingSession.project_id,
            func.sum(CodingSession.duration_mins).label("mins"),
            func.count(CodingSession.id).label("sessions"),
        )
        .filter(
            CodingSession.user_id == user.id,
            CodingSession.session_date >= date_from if date_from else True,
            CodingSession.session_date <= date_to if date_to else True,
        )
        .group_by(CodingSession.project_id)
        .all()
    )

    return {
        "total_mins": totals.total_mins or 0,
        "total_hours": round((totals.total_mins or 0) / 60, 1),
        "total_sessions": totals.total_sessions or 0,
        "per_project": [
            {
                "project_id": row.project_id,
                "total_mins": row.mins,
                "total_sessions": row.sessions,
            }
            for row in per_project
        ],
    }
