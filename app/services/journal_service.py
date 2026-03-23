from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from app.models.journal import JournalEntry
from app.models.users import User
from app.schemas.journal import JournalCreate, JournalUpdate


# ── Private helper ────────────────────────────────────────────────────────────


def _get_entry_or_404(entry_id: int, user_id: int, db: Session) -> JournalEntry:
    """
    Fetch a journal entry by ID and verify ownership.
    Same two-step pattern used throughout the project.
    """
    entry = db.query(JournalEntry).filter(JournalEntry.id == entry_id).first()

    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Journal entry {entry_id} not found",
        )

    if entry.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to access this entry",
        )

    return entry


# ── Create ────────────────────────────────────────────────────────────────────


def create_entry(data: JournalCreate, user: User, db: Session) -> JournalEntry:
    entry = JournalEntry(
        user_id=user.id,
        title=data.title,
        body=data.body,
        tags=data.tags,  # already cleaned + lowercased by the schema validator
        is_public=data.is_public,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


# ── List ──────────────────────────────────────────────────────────────────────


def list_entries(
    user: User,
    db: Session,
    tag: str | None = None,
    is_public: bool | None = None,
) -> list[JournalEntry]:
    """
    List journal entries for the current user.
    - tag: filter to entries that contain this tag (case-insensitive via lowercase storage)
    - is_public: True = only public, False = only private, None = all
    """
    query = db.query(JournalEntry).filter(JournalEntry.user_id == user.id)

    if tag is not None:
        # ARRAY contains check — works because tags are stored lowercase
        # and the schema validator lowercases incoming tags at write time.
        # This query becomes: WHERE 'debugging' = ANY(tags)
        query = query.filter(JournalEntry.tags.contains([tag.lower()]))

    if is_public is not None:
        query = query.filter(JournalEntry.is_public == is_public)

    # Most recently updated entries first
    return query.order_by(JournalEntry.updated_at.desc()).all()


# ── Get one ───────────────────────────────────────────────────────────────────


def get_entry(entry_id: int, user: User, db: Session) -> JournalEntry:
    return _get_entry_or_404(entry_id, user.id, db)


# ── Update ────────────────────────────────────────────────────────────────────


def update_entry(
    entry_id: int, data: JournalUpdate, user: User, db: Session
) -> JournalEntry:
    entry = _get_entry_or_404(entry_id, user.id, db)

    update_data = data.model_dump(exclude_unset=True)

    # Clean tags on update the same way the create validator does —
    # lowercase and deduplicate in case the client sends uncleaned tags.
    if "tags" in update_data and update_data["tags"] is not None:
        update_data["tags"] = list(
            dict.fromkeys(t.strip().lower() for t in update_data["tags"] if t.strip())
        )

    for field, value in update_data.items():
        setattr(entry, field, value)

    db.commit()
    db.refresh(entry)
    return entry


# ── Delete ────────────────────────────────────────────────────────────────────


def delete_entry(entry_id: int, user: User, db: Session) -> dict:
    entry = _get_entry_or_404(entry_id, user.id, db)
    title = entry.title  # capture before delete
    db.delete(entry)
    db.commit()
    return {"message": f"Journal entry '{title}' deleted successfully"}
