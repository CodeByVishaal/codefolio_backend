from datetime import date
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import Optional

from app.core.deps import get_db, get_current_user
from app.models.users import User
from app.schemas.session import SessionCreate, SessionUpdate, SessionResponse
from app.services import session_service

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("", status_code=201, response_model=SessionResponse)
def create_session(
    data: SessionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return session_service.create_session(data, current_user, db)


@router.get("/summary")
def get_summary(
    date_from: Optional[date] = Query(
        default=None, description="Start date (YYYY-MM-DD)"
    ),
    date_to: Optional[date] = Query(default=None, description="End date (YYYY-MM-DD)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return session_service.get_summary(current_user, db, date_from, date_to)


@router.get("", response_model=list[SessionResponse])
def list_sessions(
    project_id: Optional[int] = Query(default=None, description="Filter by project"),
    date_from: Optional[date] = Query(
        default=None, description="Start date (YYYY-MM-DD)"
    ),
    date_to: Optional[date] = Query(default=None, description="End date (YYYY-MM-DD)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return session_service.list_sessions(
        current_user, db, project_id, date_from, date_to
    )


@router.get("/{session_id}", response_model=SessionResponse)
def get_session(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return session_service.get_session(session_id, current_user, db)


@router.patch("/{session_id}", response_model=SessionResponse)
def update_session(
    session_id: int,
    data: SessionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return session_service.update_session(session_id, data, current_user, db)


@router.delete("/{session_id}")
def delete_session(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return session_service.delete_session(session_id, current_user, db)
