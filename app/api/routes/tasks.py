from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import Optional

from app.core.deps import get_db, get_current_user
from app.models.users import User
from app.models.task import TaskStatus
from app.schemas.task import TaskCreate, TaskUpdate, TaskLogTime, TaskResponse
from app.services import task_service

# prefix includes {project_id} — tasks are always accessed through a project
router = APIRouter(prefix="/projects/{project_id}/tasks", tags=["tasks"])


@router.post("", status_code=201, response_model=TaskResponse)
def create_task(
    project_id: int,
    data: TaskCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return task_service.create_task(project_id, data, current_user, db)


@router.get("", response_model=list[TaskResponse])
def list_tasks(
    project_id: int,
    status: Optional[TaskStatus] = Query(default=None, description="Filter by status"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return task_service.list_tasks(project_id, current_user, db, status_filter=status)


# Add this second router — no project_id in the prefix
user_tasks_router = APIRouter(prefix="/tasks", tags=["tasks"])


@user_tasks_router.get("", response_model=list[TaskResponse])
def list_all_tasks(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return task_service.list_all_tasks(current_user, db)


@router.patch("/{task_id}", response_model=TaskResponse)
def update_task(
    project_id: int,
    task_id: int,
    data: TaskUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return task_service.update_task(project_id, task_id, data, current_user, db)


@router.delete("/{task_id}")
def delete_task(
    project_id: int,
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return task_service.delete_task(project_id, task_id, current_user, db)


@router.post("/{task_id}/log-time", response_model=TaskResponse)
def log_time(
    project_id: int,
    task_id: int,
    data: TaskLogTime,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return task_service.log_time(project_id, task_id, data, current_user, db)
