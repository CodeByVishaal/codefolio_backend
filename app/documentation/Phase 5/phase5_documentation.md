# DevPulse — Phase 5 Documentation
## Public Profile & Private Dashboard

> **Stack:** FastAPI · SQLAlchemy ORM · PostgreSQL · Pydantic v2  
> **Phase goal:** Build the portfolio layer — a private dashboard for the authenticated user and a publicly shareable profile page that requires no login to view.

---

## Table of Contents

1. [Overview](#1-overview)
2. [The Two-Endpoint Design](#2-the-two-endpoint-design)
3. [What Data is Safe to Expose Publicly](#3-what-data-is-safe-to-expose-publicly)
4. [schemas/user.py](#4-schemasuserpY)
5. [services/user_service.py](#5-servicesuser_servicepy)
6. [routers/users.py](#6-routersuserspY)
7. [main.py — Updated](#7-mainpy--updated)
8. [SQL Patterns Introduced in Phase 5](#8-sql-patterns-introduced-in-phase-5)
9. [Request Lifecycle Walkthroughs](#9-request-lifecycle-walkthroughs)
10. [Verification & Manual Testing](#10-verification--manual-testing)
11. [Design Decisions Summary](#11-design-decisions-summary)

---

## 1. Overview

Every phase up to this point has been about collecting data — projects, tasks, sessions, journal entries. Phase 5 is about **surfacing** that data in two distinct ways:

- **Private dashboard** (`GET /api/users/me`) — the authenticated developer sees everything about themselves: email, role, all stats, verification status. This is the data that powers the user's own productivity view.

- **Public portfolio** (`GET /api/users/{id}/profile`) — anyone on the internet can view this without logging in. Only deliberately public data appears here. This is the shareable link a developer sends to a recruiter.

### Files created in this phase

```
app/
├── schemas/
│   └── user.py          ← replaced: full suite of user-facing schemas
├── services/
│   └── user_service.py  ← new: profile aggregation logic
├── routers/
│   └── users.py         ← new: two endpoints
└── main.py              ← updated: registers users router
```

### No new migration needed

Phase 5 is purely a read layer. It queries the tables created in Phases 2–4 but creates no new tables and modifies no existing ones.

### Complete endpoint list

| Method | URL | Auth required | Description |
|--------|-----|--------------|-------------|
| `GET` | `/api/users/me` | Yes | Private profile + stats for the logged-in user |
| `GET` | `/api/users/{user_id}/profile` | No | Public portfolio page — shareable link |

---

## 2. The Two-Endpoint Design

### Why two separate endpoints instead of one

The temptation is to build one endpoint and show more or less data based on whether the caller is authenticated. Avoid this. It creates a hidden branching path in a single function — hard to test, hard to reason about, and a data leak waiting to happen.

Two explicit endpoints with two distinct contracts is always cleaner:

```
GET /api/users/me              → always private, always authenticated
GET /api/users/{id}/profile    → always public, never authenticated
```

Each endpoint has one job. Each schema exactly describes what that endpoint returns. No conditional logic deciding what to include or exclude at runtime.

### The authentication asymmetry

```python
# Private — Depends(get_current_user) is required
@router.get("/me")
def get_me(current_user: User = Depends(get_current_user)): ...

# Public — no get_current_user at all
@router.get("/{user_id}/profile")
def get_public_profile(user_id: int): ...
```

The public route has **no authentication dependency**. This means:
- No cookie is read
- No JWT is decoded
- No database query for the current user
- Any HTTP client — browser, curl, Postman, a recruiter's browser — can call it

This is intentional. A portfolio page that requires login defeats its purpose.

---

## 3. What Data is Safe to Expose Publicly

This is the most important design decision in Phase 5. The answer is not "everything the user has entered" — it is "only what the user has explicitly marked public."

### What the public profile exposes

| Data | Exposed? | Why |
|------|----------|-----|
| Name | Yes | Identity on a portfolio page |
| Member since date | Yes | Shows how long they've been active |
| Public projects | Yes | Developer's portfolio showcase |
| Public journal entries | Yes | Demonstrates thinking and learning |
| Total projects count | Yes | Shows overall productivity volume |
| Total hours coded | Yes | Demonstrates commitment |
| Tasks completed | Yes | Shows execution |

### What the public profile deliberately hides

| Data | Hidden | Why |
|------|--------|-----|
| Email | Never exposed | Private contact info — prevents spam and scraping |
| Role | Never exposed | Internal system detail — meaningless to visitors |
| `is_verified` | Never exposed | Internal system detail |
| Private projects | Filtered out | User chose not to share these |
| Private journal entries | Filtered out | User chose not to share these |
| Individual session records | Aggregated only | Private activity log — only totals are shown |
| Individual task records | Aggregated only | Private work detail — only completion count shown |

### The minimum exposure principle

Only expose what is necessary for the stated purpose. The public profile's purpose is: "let a recruiter evaluate this developer." A recruiter needs to see work output, not internal system fields or private notes.

---

## 4. `schemas/user.py`

The existing `user.py` used Pydantic v1 syntax (`class Config: orm_mode = True`). This phase replaces it entirely with v2 syntax and adds all the schema shapes Phase 5 needs.

```python
from __future__ import annotations
from pydantic import BaseModel, EmailStr
from datetime import datetime
from typing import Optional
from app.models.project import ProjectStatus
```

**`from __future__ import annotations`** — makes all type annotations in this file lazy strings. Python evaluates them only when needed, not at class definition time. This prevents `NameError` when a type is referenced before it's defined — the same forward-reference problem solved with `"TaskResponse"` strings in Phase 3. Using `from __future__ import annotations` at the file level is cleaner than quoting every annotation individually.

---

### `PublicProjectSummary`

```python
class PublicProjectSummary(BaseModel):
    id:          int
    title:       str
    description: Optional[str]
    status:      ProjectStatus
    tech_stack:  list[str]
    github_url:  Optional[str]
    live_url:    Optional[str]
    created_at:  datetime

    model_config = {"from_attributes": True}
```

This is a **stripped version** of `ProjectResponse` from Phase 3. Compare what's missing:

| Field in `ProjectResponse` | In `PublicProjectSummary`? | Why removed |
|---|---|---|
| `user_id` | No | Never expose internal DB IDs in public responses |
| `is_public` | No | Redundant — if it appears here, it's obviously public |
| `updated_at` | No | Internal detail — visitors don't need edit history |

**`model_config = {"from_attributes": True}`** — this schema is populated directly from SQLAlchemy `Project` model instances returned by the database query. Pydantic needs `from_attributes=True` to read object attributes (like `project.title`) instead of dictionary keys. Every schema that maps from a SQLAlchemy object needs this.

---

### `PublicJournalSummary`

```python
class PublicJournalSummary(BaseModel):
    id:         int
    title:      str
    body:       str
    tags:       list[str]
    created_at: datetime

    model_config = {"from_attributes": True}
```

Stripped version of `JournalResponse`. Missing:

| Field in `JournalResponse` | In `PublicJournalSummary`? | Why removed |
|---|---|---|
| `user_id` | No | Internal ID — never expose publicly |
| `is_public` | No | Redundant — presence here implies it's public |
| `updated_at` | No | Internal detail irrelevant to visitors |

**`body` is included** — journal entries are meant to be read. A public entry with only a title would be useless on a portfolio page. The developer made a deliberate choice to publish this entry — the full text is what visitors should see.

---

### `PublicStats`

```python
class PublicStats(BaseModel):
    total_projects:        int
    total_public_projects: int
    total_sessions:        int
    total_hours:           float
    total_tasks_completed: int
```

A dedicated schema for the stats block inside the public profile. Notice it has **no `model_config`** — it is not mapped from a SQLAlchemy object. It is constructed directly in the service with named fields:

```python
PublicStats(
    total_projects=42,
    total_public_projects=12,
    ...
)
```

Pydantic's `from_attributes` is only needed when reading from ORM objects. Plain Python constructor calls work without it.

**Two project counts** — `total_projects` (all projects, private + public) and `total_public_projects` (public only). This shows the visitor: "This developer has 42 projects total and shares 12 of them publicly." The ratio signals how productive they are overall.

**`total_hours` is a `float`** — not `int`. The conversion from minutes (`int`) to hours (`float`) happens in the service: `round(total_mins / 60, 1)`. One decimal place: `7.5`, not `7.5000000001`. The schema declares `float` because the value may have a decimal component.

---

### `MeResponse`

```python
class MeResponse(BaseModel):
    id:           int
    name:         str
    email:        EmailStr
    role:         str
    is_verified:  bool
    created_at:   datetime
    total_projects:        int
    total_sessions:        int
    total_hours:           float
    total_tasks_completed: int

    model_config = {"from_attributes": True}
```

The private dashboard response. It includes fields that are never sent publicly:
- `email` — the user's own email, shown only to themselves
- `role` — `"developer"` or `"admin"`, useful for the frontend to show/hide admin features
- `is_verified` — lets the frontend show a "please verify your email" banner

**`role: str` not `role: UserRole`** — even though the database stores an enum, the response uses `str`. In the service we pass `user.role.value` which produces the string `"developer"`. Using `str` keeps the response schema independent of the internal enum type — the API contract is a string, not a Python enum.

**Stats are flat on `MeResponse`** — unlike `PublicProfileResponse` which nests stats inside a `PublicStats` object, `MeResponse` puts stats directly on the response. This is a deliberate difference: the private dashboard is consumed by one frontend component that wants all fields at the top level. The public profile is consumed by a portfolio page where the stats block is a distinct visual section. Schema shape should match the UI's data consumption pattern.

**`model_config = {"from_attributes": True}`** — even though `MeResponse` mixes ORM attributes (`user.id`, `user.email`) with computed values (`total_projects`, `total_hours`), it can still use `from_attributes`. Pydantic reads what it can from the object's attributes and accepts explicitly passed values for the rest. In the service, `MeResponse` is constructed with a mix:

```python
return MeResponse(
    id=user.id,           # from ORM object
    email=user.email,     # from ORM object
    total_hours=7.5,      # computed value — passed explicitly
)
```

---

### `PublicProfileResponse`

```python
class PublicProfileResponse(BaseModel):
    id:           int
    name:         str
    member_since: datetime
    stats:        PublicStats
    projects:     list[PublicProjectSummary]
    journal:      list[PublicJournalSummary]
```

The public portfolio response. Three things to notice:

**No `model_config`** — this schema is not mapped from a single SQLAlchemy object. It is assembled by the service from multiple query results and constructed explicitly. No `from_attributes` needed.

**`member_since` not `created_at`** — the field name is renamed from the database column name (`created_at`) to a user-facing label (`member_since`). On a public portfolio page, "Member since March 2025" is more meaningful than "Created at 2025-03-15T...". The service maps `user.created_at → member_since`.

**Nested objects** — `stats` is a `PublicStats` object. `projects` is a list of `PublicProjectSummary`. `journal` is a list of `PublicJournalSummary`. Pydantic validates each nested object against its own schema automatically — no manual nesting code required.

---

## 5. `services/user_service.py`

```python
from sqlalchemy.orm import Session
from sqlalchemy import func
from fastapi import HTTPException, status

from app.models.users import User
from app.models.project import Project
from app.models.task import Task, TaskStatus
from app.models.session import CodingSession
from app.models.journal import JournalEntry
from app.schemas.user import MeResponse, PublicProfileResponse, PublicStats
```

All five models are imported because the service queries all five tables to build the profile responses.

---

### `get_me`

```python
def get_me(user: User, db: Session) -> MeResponse:
```

The user object is passed in directly — it was already fetched by `get_current_user` in `deps.py`. No second user query here. The service only runs the four stat aggregation queries.

---

#### Counting projects

```python
total_projects = db.query(func.count(Project.id)).filter(
    Project.user_id == user.id
).scalar() or 0
```

**`func.count(Project.id)`** — counts the number of rows where `project_id` is not null. This generates:
```sql
SELECT COUNT(id) FROM projects WHERE user_id = ?
```

**`.scalar()`** — extracts the single value from the result. A count query returns one row with one column. `.scalar()` gives you that value directly as a Python `int` — `5`, not `(5,)` or `[(5,)]`. Using `.first()` would give a tuple; using `.all()` would give a list with one tuple. `.scalar()` is the correct method for single-value aggregate queries.

**`or 0`** — if the user has no projects, `COUNT()` returns `0` in SQL, which becomes Python `0`. However, if no rows match at all and the query returns `None` (possible with some database configurations), `None or 0` safely defaults to `0`. It's defensive — always include it on aggregate queries.

---

#### Counting sessions

```python
total_sessions = db.query(func.count(CodingSession.id)).filter(
    CodingSession.user_id == user.id
).scalar() or 0
```

Same pattern as projects. One query, one value, returned directly via `.scalar()`.

---

#### Summing minutes

```python
total_mins = db.query(func.sum(CodingSession.duration_mins)).filter(
    CodingSession.user_id == user.id
).scalar() or 0
```

**`func.sum()`** vs `func.count()`** — `COUNT` counts rows, `SUM` adds up values. `SUM(duration_mins)` generates:
```sql
SELECT SUM(duration_mins) FROM coding_sessions WHERE user_id = ?
```

**`or 0` is essential here** — `SUM()` on an empty set returns `NULL` in SQL (not `0`). If the user has no sessions, `total_mins` would be `None` without the `or 0`. Dividing `None / 60` would crash with `TypeError`. The `or 0` guard makes it safe.

**Hours conversion at the response boundary:**
```python
total_hours=round(total_mins / 60, 1),
```

All storage and computation happens in minutes (integers — exact arithmetic). The conversion to hours happens exactly once, at the point of building the response. `round(..., 1)` keeps one decimal: `7.5` not `7.500000000000001`.

---

#### Counting completed tasks through a JOIN

```python
total_tasks_completed = db.query(func.count(Task.id)).join(
    Project, Task.project_id == Project.id
).filter(
    Project.user_id == user.id,
    Task.status == TaskStatus.done,
).scalar() or 0
```

This is the most complex query in Phase 5. Tasks have no `user_id` column — ownership flows through projects. To count a user's completed tasks you must JOIN:

```sql
SELECT COUNT(tasks.id)
FROM tasks
JOIN projects ON tasks.project_id = projects.id
WHERE projects.user_id = ?
  AND tasks.status = 'done'
```

**`.join(Project, Task.project_id == Project.id)`** — the first argument is the target table (the `Project` model). The second argument is the JOIN condition. SQLAlchemy generates a SQL `JOIN` clause from this. After the join, you can filter on columns from either table.

**Why not use the SQLAlchemy relationship instead?**

You could write `user.projects` and then loop through tasks. But that would:
1. Fetch all projects into Python
2. For each project, trigger a lazy query to fetch its tasks
3. Loop through tasks in Python to count done ones

That's an N+1 query problem in a stats endpoint that could be called frequently. One SQL query with a JOIN is always preferable.

---

#### Building `MeResponse`

```python
return MeResponse(
    id=user.id,
    name=user.name,
    email=user.email,
    role=user.role.value,
    is_verified=user.is_verified,
    created_at=user.created_at,
    total_projects=total_projects,
    total_sessions=total_sessions,
    total_hours=round(total_mins / 60, 1),
    total_tasks_completed=total_tasks_completed,
)
```

**`user.role.value`** — `user.role` is a `UserRole` enum instance (`UserRole.developer`). Pydantic would serialise this as `"developer"` automatically, but passing `.value` explicitly converts it to the string `"developer"` immediately. This makes the service's output explicit and avoids relying on Pydantic's enum serialisation behaviour.

**Mixing ORM fields and computed values** — half the fields come from the `user` object, half are freshly computed integers and floats. This works cleanly in Pydantic: you pass all fields as constructor arguments. `from_attributes=True` on the schema means Pydantic can also read from object attributes, but when you pass explicit keyword arguments they take precedence.

---

### `get_public_profile`

```python
def get_public_profile(user_id: int, db: Session) -> PublicProfileResponse:
```

Unlike `get_me`, this function receives a `user_id` integer — not a `User` object. The user hasn't been loaded yet. The service must fetch the user itself, then check they exist.

---

#### Step 1 — Confirm user exists

```python
user = db.query(User).filter(User.id == user_id).first()

if not user:
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"User {user_id} not found",
    )
```

The public profile raises `404` if the user ID doesn't exist. It does **not** raise `403` — there is no ownership concept here. Any user's public profile can be viewed. The only failure case is "this user ID doesn't exist in the database".

---

#### Step 2 — Fetch public projects only

```python
public_projects = db.query(Project).filter(
    Project.user_id == user_id,
    Project.is_public == True,   # noqa: E712
).order_by(Project.updated_at.desc()).all()
```

**`Project.is_public == True`** — SQLAlchemy column comparison. This generates `WHERE is_public = true` in SQL. The `# noqa: E712` suppresses the linter warning "use `is True` instead of `== True`". In regular Python, `x is True` is correct for boolean comparisons. In SQLAlchemy column expressions, `==` is required — it generates SQL, not a Python boolean.

**`order_by(Project.updated_at.desc())`** — most recently modified public projects first. On a portfolio page, a recruiter should see your most active recent work at the top.

**`.all()`** — returns a list of `Project` model instances. These instances are passed directly to `PublicProfileResponse` where Pydantic serialises each one through `PublicProjectSummary` using `from_attributes=True`.

---

#### Step 3 — Fetch public journal entries only

```python
public_journal = db.query(JournalEntry).filter(
    JournalEntry.user_id == user_id,
    JournalEntry.is_public == True,  # noqa: E712
).order_by(JournalEntry.updated_at.desc()).all()
```

Same pattern as projects. Two filters — ownership (`user_id`) and visibility (`is_public`). Both must be true for an entry to appear.

---

#### Steps 4 — Aggregate stats

```python
total_projects = db.query(func.count(Project.id)).filter(
    Project.user_id == user_id
).scalar() or 0

total_public_projects = len(public_projects)   # already fetched above
```

**`len(public_projects)` instead of another query** — the public projects list is already in memory from Step 2. Counting its length is a free Python operation. Running another `COUNT` query would be wasteful when the data is already available.

This is an example of query result reuse — if you've already fetched data for one purpose, use it for secondary purposes before making another round trip to the database.

The remaining stats (sessions, total_mins, tasks completed) follow the same `.scalar() or 0` pattern established in `get_me`.

---

#### Step 5 — Assemble and return

```python
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
```

**`member_since=user.created_at`** — the field is renamed here. The database column is `created_at`. The public response calls it `member_since`. This renaming happens in the service, not the schema. The schema declares `member_since: datetime`. The service maps `user.created_at` to that field name.

**`PublicStats(...)` constructed inline** — `PublicStats` is a nested Pydantic model. It's constructed as a regular Python object and passed as the `stats` argument. Pydantic validates it against the `PublicStats` schema automatically.

**`projects=public_projects`** — passing a list of SQLAlchemy `Project` objects directly. Pydantic iterates the list and validates each item through `PublicProjectSummary`. Because `PublicProjectSummary` has `from_attributes=True`, Pydantic reads `project.title`, `project.tech_stack`, etc. from each object's attributes. The filtering — only `is_public=True` projects — already happened in the query. No Python-level filtering needed.

---

## 6. `routers/users.py`

```python
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_db, get_current_user
from app.models.users import User
from app.schemas.user import MeResponse, PublicProfileResponse
from app.services import user_service

router = APIRouter(prefix="/users", tags=["users"])
```

**`prefix="/users"`** — both routes start with `/users`. Combined with `prefix="/api"` in `main.py`, the full paths become `/api/users/me` and `/api/users/{user_id}/profile`.

---

### `get_me` route

```python
@router.get("/me", response_model=MeResponse)
def get_me(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return user_service.get_me(current_user, db)
```

**`Depends(get_current_user)`** — this is the authentication gate. `get_current_user` in `deps.py`:
1. Reads the `access_token` cookie
2. Decodes the JWT
3. Queries the database for the user
4. Returns the `User` object or raises `401`

If the token is missing or invalid, `get_current_user` raises `401` and this handler never runs. The `current_user` that arrives here is guaranteed to be a real, authenticated user.

**The user is already loaded** — `get_current_user` already ran a `SELECT * FROM users WHERE id = ?`. The service receives the `User` object directly and runs no additional user query. This is efficient — authentication and data loading happen in the same dependency.

**`response_model=MeResponse`** — FastAPI filters the service's return value through `MeResponse` before sending it to the client. Even if the service returned extra fields accidentally, only the declared schema fields would be sent.

---

### `get_public_profile` route

```python
@router.get("/{user_id}/profile", response_model=PublicProfileResponse)
def get_public_profile(
    user_id: int,
    db: Session = Depends(get_db),
):
    return user_service.get_public_profile(user_id, db)
```

**No `get_current_user` dependency** — this is the defining characteristic of this route. No `Depends(get_current_user)` means:
- No cookie is checked
- No JWT is decoded
- No `401` can ever be raised by the authentication layer
- Any HTTP client can call this endpoint freely

**`user_id: int` from the path** — FastAPI extracts the integer from `/{user_id}` automatically. If someone requests `/api/users/abc/profile`, FastAPI rejects it with `422` before the handler runs — `"abc"` is not a valid integer.

**`response_model=PublicProfileResponse`** — even on a public endpoint, `response_model` is critical. It ensures that even if the service accidentally returned private data, FastAPI would filter it out before sending. The schema is your last line of defence.

---

## 7. `main.py` — Updated

```python
from app.routers import auth, projects, tasks, sessions, journal, users

app.include_router(users.router, prefix="/api")
```

One new import, one new `include_router` call. The `users` router registers both the private and public endpoints under `/api/users/...`.

### Final URL map across all phases

```
/api/auth/register                         POST   Phase 1
/api/auth/login                            POST   Phase 1
/api/auth/refresh                          POST   Phase 1
/api/auth/logout                           POST   Phase 1

/api/projects                              POST   Phase 3
/api/projects                              GET    Phase 3
/api/projects/{id}                         GET    Phase 3
/api/projects/{id}                         PATCH  Phase 3
/api/projects/{id}                         DELETE Phase 3

/api/projects/{id}/tasks                   POST   Phase 3
/api/projects/{id}/tasks                   GET    Phase 3
/api/projects/{id}/tasks/{task_id}         PATCH  Phase 3
/api/projects/{id}/tasks/{task_id}         DELETE Phase 3
/api/projects/{id}/tasks/{task_id}/log-time POST  Phase 3

/api/sessions/summary                      GET    Phase 4
/api/sessions                              POST   Phase 4
/api/sessions                              GET    Phase 4
/api/sessions/{id}                         GET    Phase 4
/api/sessions/{id}                         PATCH  Phase 4
/api/sessions/{id}                         DELETE Phase 4

/api/journal                               POST   Phase 4
/api/journal                               GET    Phase 4
/api/journal/{id}                          GET    Phase 4
/api/journal/{id}                          PATCH  Phase 4
/api/journal/{id}                          DELETE Phase 4

/api/users/me                              GET    Phase 5 ← private
/api/users/{id}/profile                    GET    Phase 5 ← public
```

---

## 8. SQL Patterns Introduced in Phase 5

Phase 5 introduces two SQL patterns not seen in earlier phases.

### Pattern 1 — `.scalar()` for single-value aggregates

```python
count = db.query(func.count(Model.id)).filter(...).scalar()
total = db.query(func.sum(Model.column)).filter(...).scalar()
```

**When to use `.scalar()`** — when your query selects exactly one column and you expect exactly one row. Both conditions apply to aggregate queries with no `GROUP BY`. The return is a single Python value: an `int` for `COUNT`, an `int` or `float` for `SUM`, or `None` for empty sets.

**`.first()` vs `.scalar()`:**

```python
result = db.query(func.count(Task.id)).scalar()  # → 5 (int)
result = db.query(func.count(Task.id)).first()   # → (5,) (tuple)
```

`.scalar()` is cleaner for single-value results. `.first()` is correct when the query returns a full row (multiple columns, such as in Phase 4's per-project breakdown which returned `project_id, SUM, COUNT`).

---

### Pattern 2 — `.join()` for cross-table filtering

```python
db.query(func.count(Task.id)).join(
    Project, Task.project_id == Project.id
).filter(
    Project.user_id == user_id,
    Task.status == TaskStatus.done,
).scalar()
```

**What a JOIN does** — it combines rows from two tables based on a matching condition. `JOIN projects ON tasks.project_id = projects.id` means: "for each task row, find the project row where the IDs match, and treat them as one combined row."

After the join, you can filter on columns from either table. `Project.user_id == user_id` filters on a projects column. `Task.status == TaskStatus.done` filters on a tasks column. Both work because the JOIN made them available together.

**Why it's needed here** — tasks have no `user_id` column. The only way to ask "how many of this user's tasks are done?" is to go through projects:

```sql
SELECT COUNT(tasks.id)
FROM tasks
JOIN projects ON tasks.project_id = projects.id
WHERE projects.user_id = ?     -- ownership via project
  AND tasks.status = 'done'    -- status filter on task
```

**Why not use SQLAlchemy relationships instead?**

```python
# WRONG — N+1 queries
projects = user.projects          # SELECT all projects
for p in projects:
    for t in p.tasks:             # SELECT tasks for each project
        if t.status == "done":
            count += 1
```

For a user with 20 projects each having 10 tasks, this runs 21 queries and loads 200 task objects into Python memory just to count them. The JOIN approach does it in one query.

---

## 9. Request Lifecycle Walkthroughs

### Getting the private profile (`GET /api/users/me`)

```
GET /api/users/me
Cookie: access_token=eyJhbGc...

1. FastAPI routes to get_me() in routers/users.py

2. Depends(get_db) runs:
   → Opens a SQLAlchemy database session
   → Session available for the duration of this request

3. Depends(get_current_user) runs:
   → _get_access_token(): reads access_token cookie
   → decode_token(): verifies JWT signature, checks expiry, checks type="access"
   → payload["sub"] extracted → "3" (user ID as string)
   → SELECT * FROM users WHERE id = 3 → User(id=3, name="Alex", ...)
   → User object returned and injected as current_user

4. get_me(current_user=User(id=3), db=<session>) called
   → delegates to user_service.get_me(user, db)

5. user_service.get_me(user, db) runs four SQL queries:

   Query 1: SELECT COUNT(id) FROM projects WHERE user_id = 3
   → .scalar() → 8

   Query 2: SELECT COUNT(id) FROM coding_sessions WHERE user_id = 3
   → .scalar() → 34

   Query 3: SELECT SUM(duration_mins) FROM coding_sessions WHERE user_id = 3
   → .scalar() → 3840  (64 hours worth)

   Query 4: SELECT COUNT(tasks.id)
            FROM tasks JOIN projects ON tasks.project_id = projects.id
            WHERE projects.user_id = 3 AND tasks.status = 'done'
   → .scalar() → 47

6. MeResponse constructed:
   MeResponse(
     id=3, name="Alex", email="alex@example.com",
     role="developer", is_verified=True,
     created_at=datetime(2025, 3, 15, ...),
     total_projects=8, total_sessions=34,
     total_hours=64.0, total_tasks_completed=47
   )

7. FastAPI validates MeResponse (from_attributes=True reads object attrs)

8. Response serialised to JSON and sent:
HTTP 200
{
  "id": 3,
  "name": "Alex",
  "email": "alex@example.com",
  "role": "developer",
  "is_verified": true,
  "created_at": "2025-03-15T10:30:00",
  "total_projects": 8,
  "total_sessions": 34,
  "total_hours": 64.0,
  "total_tasks_completed": 47
}
```

Total database queries: **5** (1 for auth + 4 for stats).

---

### Getting a public profile (`GET /api/users/3/profile`)

```
GET /api/users/3/profile
(No cookie — unauthenticated request from a recruiter's browser)

1. FastAPI routes to get_public_profile() in routers/users.py
   → user_id=3 extracted from path

2. Depends(get_db) runs → session opened
   (No get_current_user — this route has no auth dependency)

3. get_public_profile(user_id=3, db=<session>) called
   → delegates to user_service.get_public_profile(3, db)

4. user_service.get_public_profile runs:

   Query 1: SELECT * FROM users WHERE id = 3
   → user found: User(id=3, name="Alex", created_at=...)
   → if not found → 404 raised here, rest of function skipped

   Query 2: SELECT * FROM projects
            WHERE user_id = 3 AND is_public = true
            ORDER BY updated_at DESC
   → [Project(id=1, title="DevPulse", ...), Project(id=4, title="Portfolio Site", ...)]
   → (2 public projects out of 8 total)

   Query 3: SELECT * FROM journal_entries
            WHERE user_id = 3 AND is_public = true
            ORDER BY updated_at DESC
   → [JournalEntry(id=2, title="Why FastAPI?", ...), ...]
   → (3 public entries out of 12 total)

   Query 4: SELECT COUNT(id) FROM projects WHERE user_id = 3
   → .scalar() → 8

   (total_public_projects = len(public_projects) = 2 — free, no query)

   Query 5: SELECT COUNT(id) FROM coding_sessions WHERE user_id = 3
   → .scalar() → 34

   Query 6: SELECT SUM(duration_mins) FROM coding_sessions WHERE user_id = 3
   → .scalar() → 3840

   Query 7: SELECT COUNT(tasks.id)
            FROM tasks JOIN projects ON tasks.project_id = projects.id
            WHERE projects.user_id = 3 AND tasks.status = 'done'
   → .scalar() → 47

5. PublicProfileResponse assembled:
   PublicProfileResponse(
     id=3,
     name="Alex",
     member_since=datetime(2025, 3, 15, ...),
     stats=PublicStats(
       total_projects=8,
       total_public_projects=2,
       total_sessions=34,
       total_hours=64.0,
       total_tasks_completed=47
     ),
     projects=[Project(id=1,...), Project(id=4,...)],
     journal=[JournalEntry(id=2,...), ...]
   )

6. FastAPI validates through PublicProfileResponse:
   → projects: each Project validated through PublicProjectSummary
   → journal: each JournalEntry validated through PublicJournalSummary
   → user_id fields stripped by schema (not declared in public schemas)
   → is_public fields stripped (not declared in public schemas)

7. Response sent — no auth header, no Set-Cookie, just data:
HTTP 200
{
  "id": 3,
  "name": "Alex",
  "member_since": "2025-03-15T10:30:00",
  "stats": {
    "total_projects": 8,
    "total_public_projects": 2,
    "total_sessions": 34,
    "total_hours": 64.0,
    "total_tasks_completed": 47
  },
  "projects": [
    {
      "id": 1,
      "title": "DevPulse",
      "description": "Developer productivity platform",
      "status": "in_progress",
      "tech_stack": ["FastAPI", "PostgreSQL", "React"],
      "github_url": "https://github.com/alex/devpulse",
      "live_url": null,
      "created_at": "2025-03-15T11:00:00"
    }
  ],
  "journal": [
    {
      "id": 2,
      "title": "Why FastAPI?",
      "body": "After evaluating Django, Flask, and FastAPI...",
      "tags": ["fastapi", "architecture"],
      "created_at": "2025-03-20T09:00:00"
    }
  ]
}
```

Total database queries: **7** (1 user lookup + 2 data fetches + 4 stat aggregations).

Notice what is **not** in the response:
- No `email`
- No `role`
- No `is_verified`
- No private projects (6 of 8 filtered out)
- No private journal entries (9 of 12 filtered out)
- No individual session records
- No individual task records

---

### Accessing private profile without auth

```
GET /api/users/me
(No cookie)

1. FastAPI routes to get_me()
2. Depends(get_current_user) runs:
   → _get_access_token(): request.cookies.get("access_token") → None
   → raise HTTPException(401, "Not authenticated. Please log in.")
3. get_me() handler never runs
4. HTTP 401 returned immediately
```

---

## 10. Verification & Manual Testing

Start the server: `uvicorn app.main:app --reload`

Open `http://localhost:8000/docs`.

### Private profile tests

**1. Get your private profile (logged in):**
```
GET /api/users/me
```
Expected: Your `id`, `name`, `email`, `role`, `is_verified`, `created_at`, and all four stat fields. The stats should reflect the data you've created across Phases 3 and 4.

**2. Verify stats accuracy:**
- `total_projects` should match your project count
- `total_sessions` should match your logged sessions
- `total_hours` should equal your total `duration_mins` across all sessions divided by 60, rounded to 1 decimal
- `total_tasks_completed` should equal the number of tasks with `status: "done"`

**3. Try without auth (from a fresh browser tab or curl):**
```bash
curl http://localhost:8000/api/users/me
```
Expected: `401` — `{"detail": "Not authenticated. Please log in."}`

---

### Public profile tests

**4. Get your public profile (note: use your actual user ID):**
```
GET /api/users/1/profile
```
Expected: A response with `name`, `member_since`, `stats` object, `projects` array, `journal` array. **Critically: no `email`, no `role`, no `is_verified`.**

**5. Privacy filter — create a private project:**
```json
POST /api/projects
{"title": "Secret Project", "is_public": false}
```
Then check `GET /api/users/1/profile`. The private project must **not** appear in `projects`. But `stats.total_projects` should be incremented — it counts all projects, not just public ones.

**6. Privacy filter — create a public project:**
```json
POST /api/projects
{"title": "Open Source Project", "is_public": true}
```
Check the public profile again. This project **must** appear in `projects` now.

**7. Journal visibility:**
Create one private journal entry (`is_public: false`) and one public one (`is_public: true`). On the public profile, only the public entry should appear in `journal`.

**8. Test 404 for non-existent user:**
```
GET /api/users/9999/profile
```
Expected: `404` — `{"detail": "User 9999 not found"}`

**9. Verify `member_since` is correct:**
The `member_since` field in the public profile should match the `created_at` shown in your private profile — they map from the same database column.

**10. Verify `total_public_projects` vs `total_projects`:**
If you have 3 projects total (2 public, 1 private):
- `stats.total_projects` → `3`
- `stats.total_public_projects` → `2`
- `projects` array → 2 items

All three numbers should be consistent.

---

## 11. Design Decisions Summary

| Decision | Reasoning |
|---|---|
| Two separate endpoints instead of one conditional one | One function, one job. No runtime branching between public and private data — eliminates accidental data leaks |
| No `get_current_user` on the public route | A portfolio page that requires login defeats its purpose — recruiters don't have accounts |
| `response_model` on the public route despite no auth | Even public endpoints should filter output through a schema — last line of defence against accidental data exposure |
| `user_id` excluded from all public schemas | Internal database IDs are never exposed in public-facing responses — minimum exposure principle |
| `is_public` excluded from `PublicProjectSummary` | Redundant — if a project appears in the public profile, it is obviously public. Declaring the field would just send `true` on every item |
| `member_since` instead of `created_at` on public response | User-facing label ("Member since March 2025") vs internal database column name — renaming happens in the service |
| Stats flat on `MeResponse`, nested on `PublicProfileResponse` | Schema shape should match UI consumption pattern. Private dashboard: all fields at one level. Public portfolio: stats is a distinct visual section |
| `PublicStats` has no `model_config` | It is constructed directly with a Python constructor, not mapped from a SQLAlchemy object. `from_attributes` is only needed for ORM-mapped schemas |
| `.scalar()` not `.first()` for aggregates | Single-value aggregate queries return one row with one column. `.scalar()` extracts the value directly — cleaner than indexing a tuple |
| JOIN for cross-table count instead of relationship traversal | One SQL query vs N+1 queries. Never loop through SQLAlchemy relationships to compute aggregates |
| `len(public_projects)` instead of a COUNT query for `total_public_projects` | The data is already in memory — reuse it. An extra database round trip for data you've already fetched is wasteful |
| `or 0` on every `.scalar()` aggregate | `SUM()` returns `NULL` on empty sets — not `0`. `None or 0` prevents `TypeError` on division and downstream arithmetic |
| Filtering at SQL level not Python level | `WHERE is_public = true` in SQL returns only the needed rows. Fetching all rows and filtering in Python wastes memory and bandwidth |

---

*Next: Phase 6 — Analytics (weekly breakdowns, coding streaks, productivity trends)*
