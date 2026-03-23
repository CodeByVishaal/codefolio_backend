from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import Optional

from app.core.deps import get_db, get_current_user
from app.models.users import User
from app.schemas.journal import JournalCreate, JournalUpdate, JournalResponse
from app.services import journal_service

router = APIRouter(prefix="/journal", tags=["journal"])


@router.post("", status_code=201, response_model=JournalResponse)
def create_entry(
    data: JournalCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return journal_service.create_entry(data, current_user, db)


@router.get("", response_model=list[JournalResponse])
def list_entries(
    tag: Optional[str] = Query(default=None, description="Filter by tag"),
    is_public: Optional[bool] = Query(
        default=None, description="True = public only, False = private only"
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return journal_service.list_entries(current_user, db, tag=tag, is_public=is_public)


@router.get("/{entry_id}", response_model=JournalResponse)
def get_entry(
    entry_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return journal_service.get_entry(entry_id, current_user, db)


@router.patch("/{entry_id}", response_model=JournalResponse)
def update_entry(
    entry_id: int,
    data: JournalUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return journal_service.update_entry(entry_id, data, current_user, db)


@router.delete("/{entry_id}")
def delete_entry(
    entry_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return journal_service.delete_entry(entry_id, current_user, db)
