from datetime import datetime, timezone
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from app.models.project import Project
from app.models.task import Task, TaskStatus
from app.models.users import User
from app.schemas.task import TaskCreate, TaskUpdate, TaskLogTime


# ── Private helpers ──────────────────────────────────────────────────────────


def _get_owned_project(project_id: int, user_id: int, db: Session) -> Project:
    """Verify the project exists and belongs to this user."""
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


def _get_task_in_project(task_id: int, project_id: int, db: Session) -> Task:
    """
    Fetch a task and confirm it belongs to the given project.
    This prevents a user from operating on task 99 (from project B)
    by calling PATCH /projects/{their_project_A}/tasks/99.
    Ownership of the project is already verified before this is called.
    """
    task = (
        db.query(Task)
        .filter(
            Task.id == task_id,
            Task.project_id == project_id,
        )
        .first()
    )

    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task {task_id} not found in project {project_id}",
        )

    return task


# ── Create ───────────────────────────────────────────────────────────────────


def create_task(project_id: int, data: TaskCreate, user: User, db: Session) -> Task:
    _get_owned_project(project_id, user.id, db)

    task = Task(
        project_id=project_id,
        title=data.title,
        description=data.description,
        status=data.status,
        priority=data.priority,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


# ── List ─────────────────────────────────────────────────────────────────────


def list_tasks(
    project_id: int,
    user: User,
    db: Session,
    status_filter: TaskStatus | None = None,
) -> list[Task]:
    _get_owned_project(project_id, user.id, db)

    query = db.query(Task).filter(Task.project_id == project_id)

    if status_filter:
        query = query.filter(Task.status == status_filter)

    return query.order_by(Task.priority.desc(), Task.created_at.asc()).all()


# ── Update ───────────────────────────────────────────────────────────────────


def update_task(
    project_id: int, task_id: int, data: TaskUpdate, user: User, db: Session
) -> Task:
    _get_owned_project(project_id, user.id, db)
    task = _get_task_in_project(task_id, project_id, db)

    update_data = data.model_dump(exclude_unset=True)

    # Status transition: when moving to "done", stamp completed_at.
    # When moving away from "done", clear it.
    if "status" in update_data:
        if update_data["status"] == TaskStatus.done and task.status != TaskStatus.done:
            task.completed_at = datetime.now(timezone.utc)
        elif update_data["status"] != TaskStatus.done:
            task.completed_at = None

    for field, value in update_data.items():
        setattr(task, field, value)

    db.commit()
    db.refresh(task)
    return task


# ── Delete ───────────────────────────────────────────────────────────────────


def delete_task(project_id: int, task_id: int, user: User, db: Session) -> dict:
    _get_owned_project(project_id, user.id, db)
    task = _get_task_in_project(task_id, project_id, db)

    db.delete(task)
    db.commit()
    return {"message": f"Task '{task.title}' deleted successfully"}


# ── Log time ─────────────────────────────────────────────────────────────────


def log_time(
    project_id: int, task_id: int, data: TaskLogTime, user: User, db: Session
) -> Task:
    """
    Add minutes to a task's time_logged total.
    This is an additive operation — it never overwrites the existing total.
    Use TaskUpdate if you need to set an absolute value.
    """
    _get_owned_project(project_id, user.id, db)
    task = _get_task_in_project(task_id, project_id, db)

    task.time_logged += data.minutes

    db.commit()
    db.refresh(task)
    return task
