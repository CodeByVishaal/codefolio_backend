from sqlalchemy.orm import Session, joinedload
from fastapi import HTTPException, status

from app.models.project import Project, ProjectStatus
from app.models.users import User
from app.schemas.project import ProjectCreate, ProjectUpdate


# ── Private helpers ──────────────────────────────────────────────────────────


def _get_project_or_404(project_id: int, user_id: int, db: Session) -> Project:
    """
    Fetch a project by ID and verify it belongs to the requesting user.
    Used by every mutating operation (update, delete) and single-item GET.

    Raises 404 if the project doesn't exist.
    Raises 403 if it exists but belongs to a different user.

    Why 404 instead of 403 for ownership failure on some operations?
    Returning 403 confirms the resource exists — an attacker learns valid IDs.
    Returning 404 reveals nothing. We use 403 here because we want clear
    error messages for the developer during API use, but in a public API
    you'd use 404 for both cases.
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
            detail="You do not have permission to access this project",
        )

    return project


# ── Create ───────────────────────────────────────────────────────────────────


def create_project(data: ProjectCreate, user: User, db: Session) -> Project:
    project = Project(
        user_id=user.id,
        title=data.title,
        description=data.description,
        status=data.status,
        tech_stack=data.tech_stack,
        github_url=data.github_url,
        live_url=data.live_url,
        is_public=data.is_public,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


# ── List ─────────────────────────────────────────────────────────────────────


def list_projects(
    user: User,
    db: Session,
    status_filter: ProjectStatus | None = None,
) -> list[Project]:
    """
    Return all projects belonging to the current user.
    Optionally filter by status (e.g. only in_progress projects).
    Tasks are NOT loaded here — use get_project() for that.
    """
    query = db.query(Project).filter(Project.user_id == user.id)

    if status_filter:
        query = query.filter(Project.status == status_filter)

    return query.order_by(Project.updated_at.desc()).all()


# ── Get one ──────────────────────────────────────────────────────────────────


def get_project(project_id: int, user: User, db: Session) -> Project:
    """
    Return a single project with its tasks eagerly loaded.
    joinedload tells SQLAlchemy to fetch tasks in the same query
    using a SQL JOIN — no separate query per project (avoids N+1).
    """
    project = (
        db.query(Project)
        .options(joinedload(Project.tasks))
        .filter(Project.id == project_id)
        .first()
    )

    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found",
        )

    if project.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to access this project",
        )

    return project


# ── Update ───────────────────────────────────────────────────────────────────


def update_project(
    project_id: int, data: ProjectUpdate, user: User, db: Session
) -> Project:
    project = _get_project_or_404(project_id, user.id, db)

    # model_dump(exclude_unset=True) only returns fields the client
    # actually sent — not fields that defaulted to None.
    # This means PATCH /projects/1 {"title": "New name"} only updates
    # title and leaves every other field untouched.
    update_data = data.model_dump(exclude_unset=True)

    for field, value in update_data.items():
        setattr(project, field, value)

    db.commit()
    db.refresh(project)
    return project


# ── Delete ───────────────────────────────────────────────────────────────────


def delete_project(project_id: int, user: User, db: Session) -> dict:
    project = _get_project_or_404(project_id, user.id, db)

    db.delete(project)
    db.commit()

    # cascade="all, delete-orphan" on Project.tasks means all tasks
    # for this project are deleted automatically by SQLAlchemy.
    # No manual cleanup needed.
    return {"message": f"Project '{project.title}' deleted successfully"}
