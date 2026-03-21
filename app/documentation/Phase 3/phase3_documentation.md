# DevPulse — Phase 3 Documentation
## Projects & Tasks API

> **Stack:** FastAPI · SQLAlchemy ORM · PostgreSQL · Pydantic v2  
> **Phase goal:** Build the first real product feature — a complete Projects and Tasks API with ownership protection, status transitions, time logging, and correct query patterns.

---

## Table of Contents

1. [Overview](#1-overview)
2. [URL Design & REST Conventions](#2-url-design--rest-conventions)
3. [The Ownership Check Pattern](#3-the-ownership-check-pattern)
4. [schemas/project.py — Updated](#4-schemasprojectpy--updated)
5. [services/project_service.py](#5-servicesproject_servicepy)
6. [routers/projects.py](#6-routersprojectspy)
7. [services/task_service.py](#7-servicestask_servicepy)
8. [routers/tasks.py](#8-routerstaskspy)
9. [main.py — Updated](#9-mainpy--updated)
10. [The Circular Import Problem & Fix](#10-the-circular-import-problem--fix)
11. [Request Lifecycle Walkthrough](#11-request-lifecycle-walkthrough)
12. [Verification & Manual Testing](#12-verification--manual-testing)
13. [Design Decisions Summary](#13-design-decisions-summary)

---

## 1. Overview

Phase 2 built the data layer — models, schemas, and the database tables. Phase 3 builds the first API surface a user can actually interact with.

After Phase 3, a user can:
- Create and manage their software projects
- Add tasks to those projects
- Update task status (todo → in_progress → done)
- Log time spent on individual tasks
- Filter projects and tasks by status

Every operation is protected by two layers: authentication (you must be logged in) and ownership (you can only touch your own data).

### Files created in this phase

```
app/
├── schemas/
│   └── project.py         ← updated: adds ProjectWithTasksResponse
├── services/
│   ├── project_service.py ← new
│   └── task_service.py    ← new
├── routers/
│   ├── projects.py        ← new
│   └── tasks.py           ← new
└── main.py                ← updated: registers new routers
```

### Complete endpoint list

| Method | URL | Description |
|--------|-----|-------------|
| `POST` | `/api/projects` | Create a project |
| `GET` | `/api/projects` | List your projects (filterable) |
| `GET` | `/api/projects/{id}` | Get one project with tasks |
| `PATCH` | `/api/projects/{id}` | Partially update a project |
| `DELETE` | `/api/projects/{id}` | Delete a project and its tasks |
| `POST` | `/api/projects/{id}/tasks` | Add a task to a project |
| `GET` | `/api/projects/{id}/tasks` | List tasks (filterable) |
| `PATCH` | `/api/projects/{id}/tasks/{task_id}` | Update a task |
| `DELETE` | `/api/projects/{id}/tasks/{task_id}` | Delete a task |
| `POST` | `/api/projects/{id}/tasks/{task_id}/log-time` | Add time to a task |

---

## 2. URL Design & REST Conventions

### Why tasks are nested under projects

```
POST /api/projects/5/tasks
GET  /api/projects/5/tasks
```

Tasks are nested resources — they can't exist without a project. The URL structure reflects this ownership. You always access tasks *through* their project.

This design gives you two guarantees at the URL level:
1. You always know which project a task belongs to from the URL alone
2. Ownership checks are always possible — the project ID is always in the request

An alternative would be `GET /api/tasks?project_id=5`. This is flat and works, but loses the ownership signal in the URL and requires extra validation to prevent cross-project access.

### HTTP method conventions

| Method | When to use | Body? | Idempotent? |
|--------|------------|-------|------------|
| `POST` | Create a new resource | Yes | No — two calls create two records |
| `GET` | Read one or many | No | Yes — repeated calls return same result |
| `PATCH` | Partial update (only sent fields) | Yes | Yes — same result if called multiple times |
| `PUT` | Full replacement (all fields required) | Yes | Yes |
| `DELETE` | Remove a resource | No | Yes — deleting twice has same result |

We use `PATCH` for updates, not `PUT`. A `PUT` would require the client to send every field on every update — even fields that didn't change. `PATCH` only requires the fields being changed. This is less error-prone and more efficient.

### Status codes used

| Code | Meaning | When we use it |
|------|---------|----------------|
| `200` | OK | Successful GET, PATCH, DELETE |
| `201` | Created | Successful POST that creates a resource |
| `403` | Forbidden | Authenticated but wrong owner |
| `404` | Not Found | Resource doesn't exist |
| `422` | Unprocessable Entity | Pydantic validation failed |

---

## 3. The Ownership Check Pattern

This is the most important pattern in Phase 3. **Every operation that reads or modifies a resource first verifies ownership.**

The pattern always has two steps:

```
Step 1: Does this resource exist?      → 404 if not
Step 2: Does it belong to this user?   → 403 if not
```

For tasks, there is a third step:

```
Step 1: Does the project exist?          → 404 if not
Step 2: Does the project belong to me?   → 403 if not
Step 3: Does the task belong to this project? → 404 if not
```

Step 3 prevents a subtle attack: a user who owns project A could otherwise call `PATCH /projects/1/tasks/99` where task `99` belongs to someone else's project B. Without checking that task 99 actually belongs to project 1, the ownership check on the project is meaningless.

---

## 4. `schemas/project.py` — Updated

The full file after Phase 3 changes:

```python
from __future__ import annotations
from pydantic import BaseModel, field_validator
from datetime import datetime
from typing import Optional, TYPE_CHECKING
from app.models.project import ProjectStatus

if TYPE_CHECKING:
    from app.schemas.task import TaskResponse


class ProjectCreate(BaseModel):
    title:       str
    description: Optional[str] = None
    status:      ProjectStatus = ProjectStatus.planning
    tech_stack:  list[str]     = []
    github_url:  Optional[str] = None
    live_url:    Optional[str] = None
    is_public:   bool          = False

    @field_validator("title")
    @classmethod
    def title_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Title cannot be blank")
        return v.strip()

    @field_validator("tech_stack")
    @classmethod
    def clean_tech_stack(cls, v: list[str]) -> list[str]:
        return list(dict.fromkeys(tag.strip().lower() for tag in v if tag.strip()))


class ProjectUpdate(BaseModel):
    title:       Optional[str]           = None
    description: Optional[str]           = None
    status:      Optional[ProjectStatus] = None
    tech_stack:  Optional[list[str]]     = None
    github_url:  Optional[str]           = None
    live_url:    Optional[str]           = None
    is_public:   Optional[bool]          = None


class ProjectResponse(BaseModel):
    """Used in list responses — tasks not included to avoid N+1 queries."""
    id:          int
    user_id:     int
    title:       str
    description: Optional[str]
    status:      ProjectStatus
    tech_stack:  list[str]
    github_url:  Optional[str]
    live_url:    Optional[str]
    is_public:   bool
    created_at:  datetime
    updated_at:  datetime

    model_config = {"from_attributes": True}


class ProjectWithTasksResponse(ProjectResponse):
    """Used on single-project GET — includes full task list."""
    tasks: list["TaskResponse"] = []

    model_config = {"from_attributes": True}


# Bottom-of-file import + model_rebuild() — the circular import fix.
# See Section 10 for full explanation.
from app.schemas.task import TaskResponse  # noqa: E402, F401

ProjectWithTasksResponse.model_rebuild()
```

### What changed from Phase 2

Phase 2 had `ProjectResponse` only. Phase 3 adds `ProjectWithTasksResponse` — a subclass of `ProjectResponse` that adds a `tasks` field.

### Why two separate response schemas

```python
class ProjectResponse(BaseModel):          # list endpoint
    # no tasks field

class ProjectWithTasksResponse(ProjectResponse):   # single-item endpoint
    tasks: list["TaskResponse"] = []
```

The list endpoint (`GET /projects`) returns many projects. If each project also loaded its tasks, SQLAlchemy would run one query per project to fetch its tasks — the **N+1 query problem**. For 20 projects, that's 21 database queries instead of 1.

The single-item endpoint (`GET /projects/5`) returns one project, so loading its tasks is perfectly reasonable — it's always just one extra JOIN.

Two schemas enforce this discipline at the type level. The router declares which schema it uses, making the behaviour explicit and impossible to accidentally mix up.

### `ProjectWithTasksResponse` inheriting `ProjectResponse`

```python
class ProjectWithTasksResponse(ProjectResponse):
    tasks: list["TaskResponse"] = []
```

Python class inheritance works here — `ProjectWithTasksResponse` gets all fields from `ProjectResponse` and adds `tasks` on top. This avoids repeating 10 field declarations. If you add a field to `ProjectResponse`, it automatically appears in `ProjectWithTasksResponse` too.

---

## 5. `services/project_service.py`

```python
from sqlalchemy.orm import Session, joinedload
from fastapi import HTTPException, status

from app.models.project import Project, ProjectStatus
from app.models.users import User
from app.schemas.project import ProjectCreate, ProjectUpdate
```

### `_get_project_or_404` — private ownership helper

```python
def _get_project_or_404(project_id: int, user_id: int, db: Session) -> Project:
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
```

**The leading underscore** on `_get_project_or_404` signals this is a private internal function — it should only be called from within `project_service.py`, never from a router directly.

**Two separate checks, two separate errors:**

The existence check comes first. If the project doesn't exist, there's no point checking ownership. The order matters — checking ownership on a `None` object would raise a Python `AttributeError`, not a clean HTTP error.

**Why not combine into one query?**

```python
# You could write this:
project = db.query(Project).filter(
    Project.id == project_id,
    Project.user_id == user_id
).first()
if not project:
    raise HTTPException(404, "Not found")
```

This is shorter but has a problem: it returns `404` even when the project exists but belongs to someone else. A user who repeatedly tries different project IDs can't tell if `404` means "doesn't exist" or "belongs to someone else." The two-check approach gives the right error code for each case.

**`f"Project {project_id} not found"`** — including the ID in the error detail helps during development and debugging. In a production API facing the public, you'd want to be less specific to avoid confirming which IDs exist.

---

### `create_project`

```python
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
```

**`user_id=user.id`** — the user ID comes from the authenticated session (`get_current_user` dependency), never from the request body. If you allowed `user_id` in the request body, a user could set it to any ID and create projects on behalf of other users.

**`db.add(project)`** — stages the object. Nothing is written to the database yet. SQLAlchemy holds it in memory.

**`db.commit()`** — writes all staged changes to the database in a single transaction. After this, the row exists with a real `id` assigned by PostgreSQL's sequence.

**`db.refresh(project)`** — re-reads the row from the database into the Python object. Required because `db.commit()` clears SQLAlchemy's in-memory state. Without `refresh()`, accessing `project.id` or `project.created_at` after a commit would raise a `DetachedInstanceError` or return stale data.

---

### `list_projects`

```python
def list_projects(
    user: User,
    db: Session,
    status_filter: ProjectStatus | None = None,
) -> list[Project]:
    query = db.query(Project).filter(Project.user_id == user.id)

    if status_filter:
        query = query.filter(Project.status == status_filter)

    return query.order_by(Project.updated_at.desc()).all()
```

**Query building is composable** — `db.query(Project)` returns a `Query` object. You can chain `.filter()` calls on it before executing. The query only runs when you call `.all()` at the end. This lets you conditionally add filters without nested if/else blocks or building SQL strings.

**`filter(Project.user_id == user.id)`** — this is the foundational security filter. It is applied unconditionally on every list call. A user can never see another user's projects, regardless of any other filter applied.

**`order_by(Project.updated_at.desc())`** — most recently modified projects appear first. This makes sense for a developer's dashboard — the project you were just working on should be at the top.

**`status_filter: ProjectStatus | None = None`** — `None` means "no filter, return all". If provided, it adds a second `.filter()` call. This pattern — optional filters with `None` as the no-op value — is the standard approach for filterable list endpoints.

---

### `get_project`

```python
def get_project(project_id: int, user: User, db: Session) -> Project:
    project = (
        db.query(Project)
        .options(joinedload(Project.tasks))
        .filter(Project.id == project_id)
        .first()
    )

    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

    if project.user_id != user.id:
        raise HTTPException(status_code=403, detail="You do not have permission")

    return project
```

**`joinedload(Project.tasks)`** — this is the key difference from the list endpoint.

Without `joinedload`, SQLAlchemy uses **lazy loading**: when you access `project.tasks`, it runs a separate `SELECT * FROM tasks WHERE project_id = ?` query at that moment. For a single project, that's fine — two queries total. But if you ever put this in a loop over many projects, each iteration fires a separate query. That's the N+1 problem.

With `joinedload`, SQLAlchemy generates a single SQL `JOIN`:

```sql
SELECT projects.*, tasks.*
FROM projects
LEFT OUTER JOIN tasks ON tasks.project_id = projects.id
WHERE projects.id = 5
```

One query, all data. The project's `tasks` list is populated before you even access it.

**Why not use `joinedload` in `list_projects` too?**

For a single project, joining tasks is always right — you need the tasks. For a list of 20 projects, joining tasks means pulling potentially hundreds of task rows for projects where you may not need them. The list endpoint returns `ProjectResponse` (no tasks) for exactly this reason.

---

### `update_project`

```python
def update_project(
    project_id: int, data: ProjectUpdate, user: User, db: Session
) -> Project:
    project = _get_project_or_404(project_id, user.id, db)

    update_data = data.model_dump(exclude_unset=True)

    for field, value in update_data.items():
        setattr(project, field, value)

    db.commit()
    db.refresh(project)
    return project
```

**`data.model_dump(exclude_unset=True)`** — this is the correct way to implement PATCH semantics.

`model_dump()` without arguments returns every field, including those that defaulted to `None`:
```python
# Client sends: {"title": "New name"}
data.model_dump()              # → {"title": "New name", "description": None, "status": None, ...}
data.model_dump(exclude_unset=True)  # → {"title": "New name"}
```

Without `exclude_unset=True`, your update loop would overwrite `description`, `status`, and every other field with `None` — wiping data the user didn't intend to change.

**`setattr(project, field, value)`** — `setattr` is a Python built-in that sets an attribute by name at runtime. `setattr(project, "title", "New name")` is equivalent to `project.title = "New name"`. It lets you iterate over a dictionary of field names and values without a long `if "title" in data` chain.

**No explicit `updated_at = datetime.now()`** — the `onupdate` lambda on the SQLAlchemy column handles this automatically when `db.commit()` runs. You never manually set `updated_at` in service code.

---

### `delete_project`

```python
def delete_project(project_id: int, user: User, db: Session) -> dict:
    project = _get_project_or_404(project_id, user.id, db)

    db.delete(project)
    db.commit()

    return {"message": f"Project '{project.title}' deleted successfully"}
```

**`db.delete(project)`** — marks the object for deletion. The actual `DELETE` SQL runs at `db.commit()`.

**Cascade is automatic** — because `Project.tasks` has `cascade="all, delete-orphan"`, SQLAlchemy automatically deletes all tasks belonging to this project before deleting the project itself. No manual cleanup code needed.

**The success message includes the title** — `project.title` is captured before the delete because after `db.commit()` the object is in a detached state. Accessing attributes on a deleted, committed object can be unreliable in some SQLAlchemy configurations. Capturing the title before the commit is a safe habit.

---

## 6. `routers/projects.py`

```python
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import Optional

from app.core.deps import get_db, get_current_user
from app.models.users import User
from app.models.project import ProjectStatus
from app.schemas.project import (
    ProjectCreate, ProjectUpdate,
    ProjectResponse, ProjectWithTasksResponse,
)
from app.services import project_service

router = APIRouter(prefix="/projects", tags=["projects"])
```

**`APIRouter(prefix="/projects", tags=["projects"])`**

- `prefix="/projects"` — every route in this file starts with `/projects`. `@router.post("")` becomes `POST /projects`. Combined with `prefix="/api"` in `main.py`, the full path is `POST /api/projects`.
- `tags=["projects"]` — groups all these routes together in the `/docs` UI under a "projects" section. Without tags, all routes appear in a single unsorted list.

---

### `create_project` route

```python
@router.post("", status_code=201, response_model=ProjectResponse)
def create_project(
    data: ProjectCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return project_service.create_project(data, current_user, db)
```

**`status_code=201`** — overrides the default `200`. HTTP `201 Created` is the correct code for a POST that creates a new resource. FastAPI defaults to `200` even for POST routes, so you must set this explicitly.

**`response_model=ProjectResponse`** — FastAPI validates and filters the return value through this schema before sending it to the client. Even if `project_service.create_project` returns a SQLAlchemy object with dozens of internal attributes, only the fields declared in `ProjectResponse` are sent. This is automatic data sanitization on every response.

**`data: ProjectCreate`** — FastAPI sees this type hint, reads the JSON request body, validates it against `ProjectCreate`, and passes the result as `data`. If validation fails (blank title, invalid status value), FastAPI returns a `422 Unprocessable Entity` automatically. The handler never runs.

**`Depends(get_current_user)`** — FastAPI runs `get_current_user()` before this handler. If the access token cookie is missing or invalid, `get_current_user` raises a `401` and the handler never runs. This is the authentication gate.

---

### `list_projects` route

```python
@router.get("", response_model=list[ProjectResponse])
def list_projects(
    status: Optional[ProjectStatus] = Query(default=None, description="Filter by status"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return project_service.list_projects(current_user, db, status_filter=status)
```

**`Query(default=None, description=...)`** — without `Query()`, FastAPI would look for `status` in the request body. `Query()` tells FastAPI this is a URL query parameter: `GET /api/projects?status=in_progress`.

The `description` appears in the `/docs` UI as a tooltip, making the API self-documenting.

**`response_model=list[ProjectResponse]`** — the response is a list, so the model is wrapped in `list[...]`. FastAPI validates each item in the list against `ProjectResponse` individually.

---

### `get_project` route

```python
@router.get("/{project_id}", response_model=ProjectWithTasksResponse)
def get_project(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return project_service.get_project(project_id, current_user, db)
```

**`/{project_id}`** — FastAPI extracts the integer from the URL path and passes it as `project_id`. If someone calls `GET /api/projects/abc` where `abc` is not an integer, FastAPI returns `422` automatically — the handler never runs.

**`response_model=ProjectWithTasksResponse`** — this is the one route that uses the richer schema. The service uses `joinedload` to fetch tasks in the same query, so `project.tasks` is populated when Pydantic serializes it.

---

### `update_project` route

```python
@router.patch("/{project_id}", response_model=ProjectResponse)
def update_project(
    project_id: int,
    data: ProjectUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return project_service.update_project(project_id, data, current_user, db)
```

**`PATCH` not `PUT`** — PATCH means partial update. Only send what changed. PUT means full replacement — you must send every field. For developer ergonomics, PATCH is almost always the right choice for update endpoints.

---

### `delete_project` route

```python
@router.delete("/{project_id}")
def delete_project(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return project_service.delete_project(project_id, current_user, db)
```

**No `response_model`** — delete endpoints return a plain message dict `{"message": "..."}`. There's no resource to model — it was just deleted. Omitting `response_model` lets FastAPI pass the dict through as-is.

---

## 7. `services/task_service.py`

```python
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from app.models.project import Project
from app.models.task import Task, TaskStatus
from app.models.users import User
from app.schemas.task import TaskCreate, TaskUpdate, TaskLogTime
```

### `_get_owned_project` — first gate

```python
def _get_owned_project(project_id: int, user_id: int, db: Session) -> Project:
    project = db.query(Project).filter(Project.id == project_id).first()

    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

    if project.user_id != user_id:
        raise HTTPException(status_code=403, detail="You do not have permission to access this project")

    return project
```

Same logic as `_get_project_or_404` in the project service. It exists here too because task operations need to validate the project first. The two services are independent — task_service doesn't call into project_service. Services don't call each other — they share database access directly.

---

### `_get_task_in_project` — second gate

```python
def _get_task_in_project(task_id: int, project_id: int, db: Session) -> Task:
    task = db.query(Task).filter(
        Task.id == task_id,
        Task.project_id == project_id,
    ).first()

    if not task:
        raise HTTPException(
            status_code=404,
            detail=f"Task {task_id} not found in project {project_id}",
        )

    return task
```

**Two conditions in a single filter** — `Task.id == task_id` AND `Task.project_id == project_id`. Both must be true for the query to return a row.

This is the cross-project access prevention check. Without `Task.project_id == project_id`:

```
User owns project 1.
Task 99 belongs to project 2 (someone else's project).
User calls PATCH /projects/1/tasks/99.
_get_owned_project passes (project 1 is theirs).
_get_task_in_project fetches task 99 by ID alone — succeeds.
User modifies another user's task. Security hole.
```

With both conditions, the query for task 99 in project 1 returns nothing — task 99 doesn't belong to project 1. Clean `404`. The hole is closed.

---

### `create_task`

```python
def create_task(
    project_id: int, data: TaskCreate, user: User, db: Session
) -> Task:
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
```

**`_get_owned_project` is called but its return value is discarded** — we only need it for the side effect of its checks. If the project doesn't exist or doesn't belong to this user, the function raises and the task creation never happens. The project object itself isn't needed for creating the task.

**No `user_id` on Task** — tasks don't have a direct user FK. The project carries the ownership. `project_id=project_id` is all that's needed to link the task correctly.

---

### `list_tasks`

```python
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
```

**`order_by(Task.priority.desc(), Task.created_at.asc())`** — two-level sort. Primary: priority descending (high → medium → low). Secondary: creation time ascending (older tasks first within same priority). This produces a natural task list — high-priority tasks at the top, and within each priority level, tasks are in the order they were created.

SQLAlchemy maps enum string values to their sort order by database storage order, not alphabetical. Since the enum is declared `high > medium > low` in the model, `.desc()` gives high first. Confirm this matches your database's enum ordering if you ever see unexpected results.

---

### `update_task`

```python
def update_task(
    project_id: int, task_id: int, data: TaskUpdate, user: User, db: Session
) -> Task:
    _get_owned_project(project_id, user.id, db)
    task = _get_task_in_project(task_id, project_id, db)

    update_data = data.model_dump(exclude_unset=True)

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
```

**Status transition logic — the most important block here:**

```python
if "status" in update_data:
    if update_data["status"] == TaskStatus.done and task.status != TaskStatus.done:
        task.completed_at = datetime.now(timezone.utc)
    elif update_data["status"] != TaskStatus.done:
        task.completed_at = None
```

This handles three cases:

| Transition | What happens |
|------------|-------------|
| Any status → `done` | `completed_at` is stamped with current time |
| `done` → any other status | `completed_at` is cleared back to `None` |
| `done` → `done` (no change) | Nothing happens — avoids overwriting the original completion time |

The second condition `task.status != TaskStatus.done` prevents overwriting the original `completed_at` if the status is already `done` and stays `done`. If you call `PATCH` with `{"status": "done"}` on a task that's already done, the first `completed_at` is preserved.

**This logic belongs in the service, never in the router.** The router's job is HTTP handling. Business rules — like "completing a task stamps a timestamp" — are business logic and live in the service layer. If you ever switch from FastAPI to another framework, the business logic survives unchanged.

---

### `log_time`

```python
def log_time(
    project_id: int, task_id: int, data: TaskLogTime, user: User, db: Session
) -> Task:
    _get_owned_project(project_id, user.id, db)
    task = _get_task_in_project(task_id, project_id, db)

    task.time_logged += data.minutes

    db.commit()
    db.refresh(task)
    return task
```

**`+=` not `=`** — this is an additive operation. Every call adds minutes to the running total. Calling `log-time` with `30` twice results in `time_logged = 60`.

If you need to correct the total (e.g. you logged 90 by mistake), use `PATCH /tasks/{id}` with `{"time_logged": <correct_value>}`. The `update_task` function handles absolute value changes. `log_time` only ever adds.

**Why a dedicated endpoint instead of just using PATCH?** Because the intent is different and enforcing it at the API level prevents mistakes. `PATCH` is for corrections. `log-time` is for incremental logging. Seeing both in `/docs` makes the API's behaviour explicit to anyone integrating with it.

---

## 8. `routers/tasks.py`

```python
router = APIRouter(prefix="/projects/{project_id}/tasks", tags=["tasks"])
```

### The nested prefix

The prefix contains a path parameter: `{project_id}`. Every route in this router automatically captures the project ID from the URL. A handler declared as:

```python
@router.post("")
def create_task(project_id: int, ...):
```

Becomes `POST /api/projects/5/tasks` and receives `project_id=5` without any extra work.

This is how FastAPI handles nested resources cleanly — the parent resource ID lives in the router prefix, not repeated on every individual route.

---

### `log-time` endpoint

```python
@router.post("/{task_id}/log-time", response_model=TaskResponse)
def log_time(
    project_id: int,
    task_id: int,
    data: TaskLogTime,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return task_service.log_time(project_id, task_id, data, current_user, db)
```

**`POST /{task_id}/log-time`** — this is a "resource action" pattern. Rather than a noun (a resource), the endpoint name describes an action on an existing resource. REST purists debate this, but it is widely used in real APIs (GitHub does this: `POST /repos/{owner}/{repo}/branches/{branch}/rename`).

The alternative would be `PATCH /{task_id}` with `{"time_logged": new_total}`. But that's ambiguous — is the client setting an absolute value or adding to it? A named action endpoint removes all ambiguity.

---

## 9. `main.py` — Updated

```python
import app.models  # noqa: F401

from app.routers import auth, projects, tasks

app.include_router(auth.router,     prefix="/api")
app.include_router(projects.router, prefix="/api")
app.include_router(tasks.router,    prefix="/api")
```

**Router registration order doesn't affect routing** — FastAPI matches routes by specificity, not registration order. `/projects/{id}` and `/projects/tasks` won't conflict.

**All three routers share `prefix="/api"`** — so the final URLs are:
- `auth.router` with its own prefix `/auth` → `/api/auth/...`
- `projects.router` with prefix `/projects` → `/api/projects/...`
- `tasks.router` with prefix `/projects/{id}/tasks` → `/api/projects/{id}/tasks/...`

---

## 10. The Circular Import Problem & Fix

### What went wrong

The original `ProjectWithTasksResponse` tried to import `TaskResponse` at the top of the file:

```python
# project.py
from app.schemas.task import TaskResponse   # import at top

class ProjectWithTasksResponse(ProjectResponse):
    tasks: list[TaskResponse] = []          # used immediately
```

When Python imports `project.py`, it hits the `TaskResponse` import and goes to load `task.py`. If `task.py` then imports anything from `project.py` — directly or indirectly — you get a circular import. Python can't finish loading either file.

Even without a direct circular import, the issue is that Pydantic evaluates the type annotation `list[TaskResponse]` at class definition time. If `TaskResponse` isn't defined yet for any reason, you get `NameError: name 'TaskResponse' is not defined`.

### The fix: forward reference + bottom import + `model_rebuild()`

```python
class ProjectWithTasksResponse(ProjectResponse):
    tasks: list["TaskResponse"] = []    # Step 1: string = deferred resolution
    model_config = {"from_attributes": True}


# Step 2: import the real class AFTER the class body is fully defined
from app.schemas.task import TaskResponse  # noqa: E402, F401

# Step 3: tell Pydantic to now resolve all deferred string annotations
ProjectWithTasksResponse.model_rebuild()
```

**Step 1 — `"TaskResponse"` as a string:**

Quoting a type annotation creates a **forward reference**. Pydantic stores the string `"TaskResponse"` instead of the actual class. It does not try to resolve it at class definition time. No `NameError`.

**Step 2 — bottom-of-file import:**

The import runs after the class body is complete. At this point, `TaskResponse` is available in the module namespace.

**Step 3 — `model_rebuild()`:**

This is Pydantic's instruction to "go back and resolve all the forward references now." It walks the class's annotations, finds `"TaskResponse"`, looks it up in the current namespace (where it now exists from Step 2), and replaces the string reference with the actual class.

Without `model_rebuild()`, the forward reference stays unresolved and Pydantic raises:

```
PydanticUserError: `ProjectWithTasksResponse` is not fully defined;
you should define `TaskResponse` and all referenced types,
then call `.rebuild()` on the instance.
```

### `# noqa: E402, F401` explained

- `E402` — "module level import not at top of file". Suppresses the linting warning for the bottom-of-file import.
- `F401` — "imported but unused". The `TaskResponse` import is used inside the string annotation and by `model_rebuild()`, but the linter can't see that statically.

Both suppressions are intentional and documented by the comment. This is not sloppy code — it is the standard Pydantic v2 pattern for cross-referencing schemas.

---

## 11. Request Lifecycle Walkthrough

### Creating a project

```
POST /api/projects
Cookie: access_token=eyJ...
Body: {"title": "DevPulse Backend", "tech_stack": ["FastAPI", "PostgreSQL"]}

1. FastAPI routes to create_project() in routers/projects.py

2. Depends(get_current_user) runs:
   → reads access_token cookie
   → decodes JWT, extracts user_id
   → queries users table: SELECT * FROM users WHERE id = ?
   → returns User object

3. FastAPI parses body against ProjectCreate:
   → title: "DevPulse Backend" — validator strips whitespace, passes
   → tech_stack: ["FastAPI", "PostgreSQL"] — validator deduplicates, passes
   → All other fields: defaults applied (status=planning, is_public=false)
   → If validation fails → 422 returned, handler never runs

4. project_service.create_project(data, current_user, db) called:
   → Project object constructed with user_id=current_user.id
   → db.add(project)
   → db.commit() — INSERT INTO projects ... executed
   → db.refresh(project) — row re-read, id and created_at populated
   → Project object returned

5. FastAPI serializes through ProjectResponse:
   → Only declared fields included
   → SQLAlchemy model attributes read via from_attributes=True
   → JSON response built

6. Response sent:
HTTP 201
{"id": 1, "user_id": 3, "title": "DevPulse Backend", "status": "planning", ...}
```

---

### Completing a task

```
PATCH /api/projects/1/tasks/2
Cookie: access_token=eyJ...
Body: {"status": "done"}

1. FastAPI routes to update_task() in routers/tasks.py
   → project_id=1, task_id=2 extracted from URL

2. Depends(get_current_user) runs → returns User

3. Body parsed against TaskUpdate:
   → {"status": "done"} — only status is set, all others are unset
   → Pydantic stores which fields were explicitly provided

4. task_service.update_task(1, 2, data, user, db) called:

   a. _get_owned_project(1, user.id, db):
      → SELECT * FROM projects WHERE id = 1
      → project.user_id == user.id → OK

   b. _get_task_in_project(2, 1, db):
      → SELECT * FROM tasks WHERE id = 2 AND project_id = 1
      → Task found → OK

   c. update_data = data.model_dump(exclude_unset=True)
      → {"status": "done"}  (not {"status": "done", "title": None, ...})

   d. "status" in update_data → True
      update_data["status"] == TaskStatus.done → True
      task.status != TaskStatus.done → True (was "todo")
      → task.completed_at = datetime.now(timezone.utc)  ← stamped

   e. setattr(task, "status", "done")

   f. db.commit() — UPDATE tasks SET status='done', completed_at=NOW() WHERE id=2
   g. db.refresh(task)

5. TaskResponse serialization → sent to client
HTTP 200
{"id": 2, "status": "done", "completed_at": "2026-03-19T14:32:00Z", "time_logged": 0, ...}
```

---

### Attempting to access another user's project

```
GET /api/projects/5
Cookie: access_token=eyJ... (user_id=3 in token)

Project 5 belongs to user_id=7.

1. get_current_user → User(id=3)
2. project_service.get_project(5, user, db):
   → SELECT * FROM projects WHERE id = 5 → found (belongs to user 7)
   → project.user_id (7) != user.id (3)
   → raise HTTPException(403, "You do not have permission")
3. Handler stops. Response:
HTTP 403
{"detail": "You do not have permission to access this project"}
```

---

## 12. Verification & Manual Testing

Start the server and open `http://localhost:8000/docs`. Test in this sequence — each step depends on the previous.

### Step 1 — Authenticate

`POST /api/auth/login` with your credentials. The session cookie is set automatically by the browser in `/docs`.

---

### Step 2 — Create a project

```json
POST /api/projects
{
  "title": "DevPulse Backend",
  "description": "FastAPI backend API",
  "tech_stack": ["FastAPI", "PostgreSQL", "SQLAlchemy"],
  "status": "in_progress",
  "is_public": true
}
```

Expected: `201` with a project object. Note the `id` — you'll need it for task operations.

**Also verify the validator** — try sending `{"title": "   "}` (spaces only). Expected: `422` with detail about blank title.

---

### Step 3 — List projects

```
GET /api/projects
GET /api/projects?status=in_progress
GET /api/projects?status=planning
```

Expected: first two return your project, third returns an empty array (no projects in `planning` status).

---

### Step 4 — Get one project

```
GET /api/projects/1
```

Expected: project object with `"tasks": []`. The `tasks` key must be present and empty — this confirms `ProjectWithTasksResponse` is being used correctly.

---

### Step 5 — Add tasks

```json
POST /api/projects/1/tasks
{"title": "Set up database models", "priority": "high", "status": "done"}
```

Expected: `201`. Check that `completed_at` is **not** null — it should be auto-stamped because `status` is `done`.

```json
POST /api/projects/1/tasks
{"title": "Write auth service", "priority": "high"}
```

Expected: `201` with `status: "todo"` and `completed_at: null`.

---

### Step 6 — Get project with tasks

```
GET /api/projects/1
```

Expected: project object with `"tasks"` array containing both tasks you just created. Tasks should be sorted high-priority first.

---

### Step 7 — Update a task status

```json
PATCH /api/projects/1/tasks/2
{"status": "done"}
```

Expected: task with `completed_at` now stamped. Move it back:

```json
PATCH /api/projects/1/tasks/2
{"status": "in_progress"}
```

Expected: `completed_at` is now `null` again.

---

### Step 8 — Log time

```json
POST /api/projects/1/tasks/1/log-time
{"minutes": 90}
```

Expected: `time_logged: 90`. Call it again with `{"minutes": 60}`. Expected: `time_logged: 150`.

---

### Step 9 — Ownership check

Try accessing a project ID that doesn't exist:
```
GET /api/projects/9999
```
Expected: `404`.

If you have a second account, try accessing its project while logged in as the first account. Expected: `403`.

---

### Step 10 — Delete

```
DELETE /api/projects/1
```

Expected: `200` with a success message. Try `GET /api/projects/1` afterwards. Expected: `404`. The tasks are gone too — confirmed by the cascade.

---

## 13. Design Decisions Summary

| Decision | Reasoning |
|---|---|
| Two response schemas: `ProjectResponse` and `ProjectWithTasksResponse` | Prevents N+1 queries on list endpoints — tasks only load for single-project GETs |
| `joinedload(Project.tasks)` only on single-project GET | Single JOIN vs N separate lazy queries. Never use lazy loading in a list |
| `_get_project_or_404` as a private helper | Ownership check logic written once, called everywhere — DRY and consistent |
| `_get_task_in_project` filters by both `task_id` AND `project_id` | Prevents cross-project task access even when the parent project is owned by you |
| `model_dump(exclude_unset=True)` for PATCH | Only sent fields are updated — unset fields never overwrite existing data with None |
| `completed_at` set in service, not router | Business rules belong in services — routers only handle HTTP concerns |
| `log_time` as additive `+=` with its own endpoint | Separates "set absolute value" (PATCH) from "add to total" (log-time) — intent is unambiguous |
| Task ordering: priority desc, created_at asc | High-priority tasks surface first; within same priority, older tasks first |
| `user_id` from token, never from request body | Prevents users from creating or accessing resources as other users |
| Named action endpoint `log-time` over generic PATCH | Explicit intent — no ambiguity about whether the value is absolute or additive |
| Services don't call other services | Services access the database directly — no inter-service coupling, easier to test |

---

*Next: Phase 4 — Coding Sessions & Journal API*
