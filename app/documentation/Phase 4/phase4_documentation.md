# DevPulse — Phase 4 Documentation
## Coding Sessions & Journal API

> **Stack:** FastAPI · SQLAlchemy ORM · PostgreSQL · Pydantic v2  
> **Phase goal:** Build the data collection layer — log coding sessions with date-range filtering and summary aggregation, and manage a developer journal with tag-based filtering and public/private visibility.

---

## Table of Contents

1. [Overview](#1-overview)
2. [What's New in Phase 4](#2-whats-new-in-phase-4)
3. [URL Design & Routing Rules](#3-url-design--routing-rules)
4. [services/session_service.py](#4-servicessession_servicepy)
5. [routers/sessions.py](#5-routerssessionspy)
6. [services/journal_service.py](#6-servicesjournal_servicepy)
7. [routers/journal.py](#7-routersjournalpy)
8. [main.py — Updated](#8-mainpy--updated)
9. [Request Lifecycle Walkthroughs](#9-request-lifecycle-walkthroughs)
10. [Verification & Manual Testing](#10-verification--manual-testing)
11. [Design Decisions Summary](#11-design-decisions-summary)

---

## 1. Overview

Phase 3 gave users a way to organise work — projects and tasks. Phase 4 gives users a way to **record work** — coding sessions and journal entries. These two features are the data sources that everything downstream depends on.

- **Coding sessions** answer: *How much time did I code? When? On what?*
- **Journal entries** answer: *What did I learn? What problems did I solve?*

Phase 6 (analytics) will aggregate coding sessions into charts and streaks. Phase 5 (public profile) will expose public journal entries to recruiters. Both of those phases require this data to exist first.

### Files created in this phase

```
app/
├── services/
│   ├── session_service.py   ← new
│   └── journal_service.py   ← new
├── routers/
│   ├── sessions.py          ← new
│   └── journal.py           ← new
└── main.py                  ← updated: registers two new routers
```

### No new migration needed

Both `coding_sessions` and `journal_entries` tables were created in the Phase 2 migration. Phase 4 only adds the service and router layer on top of existing tables.

### Complete endpoint list

| Method | URL | Auth | Description |
|--------|-----|------|-------------|
| `POST` | `/api/sessions` | Required | Log a coding session |
| `GET` | `/api/sessions/summary` | Required | Aggregated totals for a date range |
| `GET` | `/api/sessions` | Required | List sessions with optional filters |
| `GET` | `/api/sessions/{id}` | Required | Get one session |
| `PATCH` | `/api/sessions/{id}` | Required | Update a session |
| `DELETE` | `/api/sessions/{id}` | Required | Delete a session |
| `POST` | `/api/journal` | Required | Create a journal entry |
| `GET` | `/api/journal` | Required | List entries with optional filters |
| `GET` | `/api/journal/{id}` | Required | Get one entry |
| `PATCH` | `/api/journal/{id}` | Required | Update an entry |
| `DELETE` | `/api/journal/{id}` | Required | Delete an entry |

---

## 2. What's New in Phase 4

### New pattern: optional foreign key validation

Sessions have an optional `project_id`. When provided, the service must verify the user owns that project before creating the link. This is a new ownership pattern — in Phase 3, every resource had a required owner. Here, the link is optional but when present it still needs protection.

### New pattern: SQL aggregation functions

The `/sessions/summary` endpoint uses `func.sum()` and `func.count()` — SQLAlchemy wrappers that run aggregation inside the database. Instead of fetching all rows into Python and summing them in a loop, a single `SELECT SUM(...), COUNT(...)` query does the work. This pattern previews Phase 6 (full analytics).

### New pattern: ARRAY contains query

Journal entries have a `tags` column of type `ARRAY(String)`. Filtering by tag uses `.contains([tag])` — SQLAlchemy's array containment operator. This generates native PostgreSQL `= ANY(tags)` SQL — clean, indexed, and accurate. No `LIKE '%tag%'` hacks.

### Familiar patterns from Phase 3

- Private `_get_X_or_404` helpers with the same two-step existence + ownership check
- `model_dump(exclude_unset=True)` for PATCH semantics
- `order_by` for consistent list ordering
- `status_code=201` on POST routes
- `response_model=` on every route

---

## 3. URL Design & Routing Rules

### Sessions are flat, not nested

```
POST /api/sessions         (not /api/projects/1/sessions)
GET  /api/sessions
```

In Phase 3, tasks were nested under projects because a task cannot exist without a project. Sessions are different — they have an **optional** project link. A session without a project is valid and common (general learning, exploration, reading). Nesting under a project would make project-less sessions impossible to express.

Instead, project association is expressed as a query filter on the list endpoint and a body field on create:

```
GET /api/sessions?project_id=1   ← filter by project
POST /api/sessions {"project_id": 1, ...}  ← create linked to project
```

### The `/summary` route must be declared before `/{session_id}`

```python
# routers/sessions.py — ORDER MATTERS

@router.get("/summary")          # ← declared first
def get_summary(...): ...

@router.get("/{session_id}")     # ← declared second
def get_session(...): ...
```

FastAPI matches routes in declaration order. If `/{session_id}` is declared first, a request to `GET /api/sessions/summary` matches it — FastAPI tries to parse `"summary"` as an integer and returns:

```json
{"detail": [{"type": "int_parsing", "loc": ["path", "session_id"], "msg": "Input should be a valid integer"}]}
```

By declaring `/summary` first, FastAPI matches the literal string before attempting the dynamic integer pattern. This is a common bug in FastAPI applications — always declare literal paths before parameterised ones when they share a prefix.

---

## 4. `services/session_service.py`

```python
from datetime import date
from sqlalchemy.orm import Session
from sqlalchemy import func
from fastapi import HTTPException, status

from app.models.session import CodingSession
from app.models.project import Project
from app.models.users import User
from app.schemas.session import SessionCreate, SessionUpdate
```

**`from sqlalchemy import func`** — `func` is SQLAlchemy's gateway to SQL functions. `func.sum(...)` generates `SUM(...)`, `func.count(...)` generates `COUNT(...)`. Any SQL function can be called through `func` — SQLAlchemy passes it directly to the database dialect. Used in `get_summary`.

---

### `_get_session_or_404`

```python
def _get_session_or_404(session_id: int, user_id: int, db: Session) -> CodingSession:
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
```

The same two-step pattern established in Phase 3. Existence check first — if the row doesn't exist, there is nothing to check ownership against. Ownership check second — the session exists but belongs to someone else.

The separation into two checks matters for error correctness:
- `404` — resource does not exist
- `403` — resource exists, requester is not allowed

Collapsing both into one query (`WHERE id = ? AND user_id = ?`) would always return `404` regardless of which condition failed. An authenticated user who calls `GET /sessions/99` where session 99 belongs to someone else would get `404` instead of `403`. While some APIs prefer this for security (hiding that a resource exists), we use separate errors here for cleaner developer experience during building.

---

### `_validate_project_ownership`

```python
def _validate_project_ownership(project_id: int, user_id: int, db: Session) -> None:
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
```

This helper is unique to Phase 4. It has no equivalent in Phase 3 because all Phase 3 resources had required, not optional, foreign keys.

**The problem it solves:** Without this check, a user could call:

```json
POST /api/sessions
{"duration_mins": 60, "session_date": "2026-03-23", "project_id": 99}
```

Where project `99` belongs to a different user. The session would be created, linked to that user's project. The attacker's session would now appear in that project's per-project breakdown. Data from one user pollutes another user's analytics.

**Return type is `None`** — this function exists purely for its side effect (raising an exception if validation fails). If it returns without raising, validation passed. The caller discards the return value.

---

### `create_session`

```python
def create_session(data: SessionCreate, user: User, db: Session) -> CodingSession:
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
```

**`if data.project_id is not None:`** — the project validation only runs when a project is being linked. A session without a project (`project_id=None`) skips validation entirely. The `is not None` check is deliberate — `if data.project_id:` would also skip validation if `project_id=0`, which is not a valid ID but is falsy. `is not None` is explicit and unambiguous.

**`user_id=user.id`** — same rule as Phase 3: the user ID always comes from the authenticated session, never from the request body. No client-provided `user_id` field exists on `SessionCreate`.

---

### `list_sessions`

```python
def list_sessions(
    user: User,
    db: Session,
    project_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[CodingSession]:
    query = db.query(CodingSession).filter(CodingSession.user_id == user.id)

    if project_id is not None:
        query = query.filter(CodingSession.project_id == project_id)

    if date_from is not None:
        query = query.filter(CodingSession.session_date >= date_from)

    if date_to is not None:
        query = query.filter(CodingSession.session_date <= date_to)

    return query.order_by(CodingSession.session_date.desc()).all()
```

**Three optional filters, all composable** — the base query always filters by `user_id`. Each additional filter is applied only when the parameter is not `None`. The query object is mutable — each `.filter()` call adds a `WHERE` clause and returns the modified query. `.all()` at the end executes the final assembled SQL.

**`>= date_from` and `<= date_to`** — inclusive on both ends. A request for `?date_from=2026-03-01&date_to=2026-03-31` returns sessions on March 1st and March 31st as well as everything in between. This is the natural expectation for a calendar range filter.

**Why filter on `session_date` not `created_at`?** Developers log sessions retrospectively. A session coded at 11pm Sunday might be logged Monday morning. `created_at` would place it on Monday. `session_date` places it on Sunday — the correct day for analytics like "how many hours did I code on Sunday?".

**`order_by(CodingSession.session_date.desc())`** — most recent sessions first. This is a log/timeline view — you always want to see your latest session at the top, not your oldest.

---

### `get_session`

```python
def get_session(session_id: int, user: User, db: Session) -> CodingSession:
    return _get_session_or_404(session_id, user.id, db)
```

A one-liner that delegates entirely to the private helper. It exists as a named public function because:

1. The router calls `session_service.get_session(...)` — a named function with a clear contract
2. If the logic ever needs to grow (e.g. eager-loading related data), it grows here without touching the router

---

### `update_session`

```python
def update_session(
    session_id: int, data: SessionUpdate, user: User, db: Session
) -> CodingSession:
    coding_session = _get_session_or_404(session_id, user.id, db)

    update_data = data.model_dump(exclude_unset=True)

    if "project_id" in update_data and update_data["project_id"] is not None:
        _validate_project_ownership(update_data["project_id"], user.id, db)

    for field, value in update_data.items():
        setattr(coding_session, field, value)

    db.commit()
    db.refresh(coding_session)
    return coding_session
```

**Project validation on update** — if the client sends a new `project_id`, the same ownership check that runs on create also runs on update. The check only fires when `project_id` is in the update payload AND is not `None`. This covers three cases:

| Client sends | What happens |
|---|---|
| `{"duration_mins": 120}` | No project change — validation skipped |
| `{"project_id": 5}` | New project link — ownership of project 5 checked |
| `{"project_id": null}` | Unlinking the project — no project to validate |

Setting `project_id` to `null` explicitly unlinks the session from any project. This is valid — a developer might realise a session wasn't really tied to a project. The check `update_data["project_id"] is not None` handles this case: `null` means "unlink", not "validate nothing".

---

### `delete_session`

```python
def delete_session(session_id: int, user: User, db: Session) -> dict:
    coding_session = _get_session_or_404(session_id, user.id, db)
    db.delete(coding_session)
    db.commit()
    return {"message": "Session deleted successfully"}
```

No cascade concerns here — sessions have no child relationships. `db.delete(coding_session)` marks it for deletion, `db.commit()` executes the `DELETE` SQL. Unlike projects (which cascade to tasks), deleting a session affects only that single row.

---

### `get_summary`

```python
def get_summary(
    user: User,
    db: Session,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict:
    totals = db.query(
        func.sum(CodingSession.duration_mins).label("total_mins"),
        func.count(CodingSession.id).label("total_sessions"),
    ).filter(
        CodingSession.user_id == user.id,
        CodingSession.session_date >= date_from if date_from else True,
        CodingSession.session_date <= date_to if date_to else True,
    ).first()

    per_project = db.query(
        CodingSession.project_id,
        func.sum(CodingSession.duration_mins).label("mins"),
        func.count(CodingSession.id).label("sessions"),
    ).filter(
        CodingSession.user_id == user.id,
        CodingSession.session_date >= date_from if date_from else True,
        CodingSession.session_date <= date_to if date_to else True,
    ).group_by(CodingSession.project_id).all()

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
```

This function introduces SQL aggregation — the most important new concept in Phase 4.

---

#### `func.sum()` and `func.count()`

```python
db.query(
    func.sum(CodingSession.duration_mins).label("total_mins"),
    func.count(CodingSession.id).label("total_sessions"),
)
```

`func.sum(CodingSession.duration_mins)` generates `SUM(coding_sessions.duration_mins)` in SQL. The entire aggregation runs inside PostgreSQL — no rows are fetched into Python.

**Why this matters — contrast with the naive approach:**

```python
# WRONG — fetches all rows into Python, sums in a loop
sessions = db.query(CodingSession).filter(...).all()
total = sum(s.duration_mins for s in sessions)  # Python loop
```

For a user with 500 sessions, this fetches 500 rows from the database across the network just to sum one column. With `func.sum()`:

```sql
SELECT SUM(duration_mins), COUNT(id) FROM coding_sessions WHERE user_id = ?
```

One row returned. One network round trip. Hundreds of times faster for large datasets.

**`.label("total_mins")`** — gives the aggregated column a name so you can access it as `result.total_mins` instead of `result[0]`. Without `.label()`, the column would be accessible only by positional index, which is fragile.

---

#### `.first()` vs `.all()` on aggregation queries

```python
totals = db.query(func.sum(...), func.count(...)).filter(...).first()
```

An aggregation query without `GROUP BY` always returns exactly one row — the aggregate across all matching rows. `.first()` is correct here. `.all()` would return a list with one element, requiring `result[0].total_mins` — unnecessary indirection.

---

#### `totals.total_mins or 0`

```python
"total_mins": totals.total_mins or 0,
```

`SUM()` on an empty set returns `NULL` in SQL, which becomes `None` in Python. If the user has no sessions in the given date range, `totals.total_mins` is `None`. `None or 0` evaluates to `0` — a clean default value instead of `null` in the JSON response.

---

#### `GROUP BY` for per-project breakdown

```python
per_project = db.query(
    CodingSession.project_id,
    func.sum(CodingSession.duration_mins).label("mins"),
    func.count(CodingSession.id).label("sessions"),
).filter(...).group_by(CodingSession.project_id).all()
```

`GROUP BY CodingSession.project_id` splits the rows into groups — one group per unique `project_id`. `SUM` and `COUNT` are applied to each group separately. The result is one row per project, each with its total minutes and session count.

Generated SQL:
```sql
SELECT project_id, SUM(duration_mins) AS mins, COUNT(id) AS sessions
FROM coding_sessions
WHERE user_id = ?
GROUP BY project_id
```

This is the foundational pattern behind every analytics chart in Phase 6. The same structure — filter, group, aggregate — is used for daily totals, weekly summaries, and streak calculations.

---

#### `round(..., 1)` for display-ready hours

```python
"total_hours": round((totals.total_mins or 0) / 60, 1),
```

`210 minutes / 60 = 3.5 hours`. `round(..., 1)` keeps one decimal place — `3.5` not `3.5000000000000004` (floating point). This is the only place where minutes are converted to hours. All storage and computation stays in minutes; conversion happens at the response boundary.

---

## 5. `routers/sessions.py`

```python
from datetime import date
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import Optional

from app.core.deps import get_db, get_current_user
from app.models.users import User
from app.schemas.session import SessionCreate, SessionUpdate, SessionResponse
from app.services import session_service

router = APIRouter(prefix="/sessions", tags=["sessions"])
```

---

### `create_session` route

```python
@router.post("", status_code=201, response_model=SessionResponse)
def create_session(
    data: SessionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return session_service.create_session(data, current_user, db)
```

`SessionCreate` includes the Pydantic validators from Phase 2 — `duration_mins` must be between 1 and 1440, `session_date` is automatically parsed from an ISO 8601 string. If either fails, FastAPI returns `422` before the service is called.

---

### `get_summary` route — must be first

```python
@router.get("/summary")
def get_summary(
    date_from: Optional[date] = Query(default=None, description="Start date (YYYY-MM-DD)"),
    date_to:   Optional[date] = Query(default=None, description="End date (YYYY-MM-DD)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return session_service.get_summary(current_user, db, date_from, date_to)
```

**No `response_model`** — the summary returns a plain dict with a custom shape (`total_mins`, `total_hours`, `total_sessions`, `per_project`). There's no Pydantic model for this shape yet. FastAPI serialises plain dicts without a `response_model` by passing them through as JSON directly. A dedicated `SummaryResponse` schema could be added later for stronger typing.

**`date` as a `Query` parameter** — FastAPI and Pydantic handle `date` type parameters automatically. When the client sends `?date_from=2026-03-01`, Pydantic parses the string into a `datetime.date` object. Invalid formats (`?date_from=not-a-date`) produce a `422` automatically.

---

### `list_sessions` route

```python
@router.get("", response_model=list[SessionResponse])
def list_sessions(
    project_id: Optional[int]  = Query(default=None, description="Filter by project"),
    date_from:  Optional[date] = Query(default=None, description="Start date (YYYY-MM-DD)"),
    date_to:    Optional[date] = Query(default=None, description="End date (YYYY-MM-DD)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return session_service.list_sessions(current_user, db, project_id, date_from, date_to)
```

Three independent query parameters, all optional. Any combination is valid:

```
GET /api/sessions                                         → all sessions
GET /api/sessions?project_id=1                            → project 1 only
GET /api/sessions?date_from=2026-03-01                    → from March 1st
GET /api/sessions?date_from=2026-03-01&date_to=2026-03-31 → all of March
GET /api/sessions?project_id=1&date_from=2026-03-01       → project 1 in March
```

All combinations work because the service applies each filter independently only when the value is not `None`.

---

### `get_session`, `update_session`, `delete_session`

```python
@router.get("/{session_id}", response_model=SessionResponse)
def get_session(session_id: int, ...): ...

@router.patch("/{session_id}", response_model=SessionResponse)
def update_session(session_id: int, data: SessionUpdate, ...): ...

@router.delete("/{session_id}")
def delete_session(session_id: int, ...): ...
```

Same structure as Phase 3 — path parameter for the ID, `response_model` on GET and PATCH, no `response_model` on DELETE. Nothing new here beyond what Phase 3 established.

---

## 6. `services/journal_service.py`

```python
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from app.models.journal import JournalEntry
from app.models.users import User
from app.schemas.journal import JournalCreate, JournalUpdate
```

---

### `_get_entry_or_404`

```python
def _get_entry_or_404(entry_id: int, user_id: int, db: Session) -> JournalEntry:
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
```

Identical pattern to every other `_get_X_or_404` in the project. By Phase 4 this pattern is established — you recognise it immediately across all services.

---

### `create_entry`

```python
def create_entry(data: JournalCreate, user: User, db: Session) -> JournalEntry:
    entry = JournalEntry(
        user_id=user.id,
        title=data.title,
        body=data.body,
        tags=data.tags,
        is_public=data.is_public,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry
```

**`tags=data.tags`** — by the time `data.tags` arrives here, it has already been cleaned by the `clean_tags` validator on `JournalCreate`. The tags are lowercased, stripped of whitespace, and deduplicated. The service trusts the schema's output and stores it directly. This is the separation of concerns working correctly — validation happens in schemas, persistence happens in services.

---

### `list_entries`

```python
def list_entries(
    user: User,
    db: Session,
    tag: str | None = None,
    is_public: bool | None = None,
) -> list[JournalEntry]:
    query = db.query(JournalEntry).filter(JournalEntry.user_id == user.id)

    if tag is not None:
        query = query.filter(JournalEntry.tags.contains([tag.lower()]))

    if is_public is not None:
        query = query.filter(JournalEntry.is_public == is_public)

    return query.order_by(JournalEntry.updated_at.desc()).all()
```

#### `JournalEntry.tags.contains([tag.lower()])`

This is the ARRAY containment query. Breaking it down:

**`[tag.lower()]`** — wraps the tag in a list. `.contains()` on a PostgreSQL ARRAY column checks whether the column's array contains all elements of the provided list. `[tag.lower()]` is a list with one element — "does the tags array contain this tag?".

**`.lower()`** — ensures the query tag is lowercase before comparison. Tags are stored lowercase (the `clean_tags` validator lowercases them at write time). If a user queries `?tag=Debugging`, this becomes `.contains(["debugging"])`, which correctly matches stored tags like `["debugging", "sqlalchemy"]`.

**Generated SQL:**

```sql
WHERE 'debugging' = ANY(tags)
```

`= ANY(array)` is PostgreSQL's native array containment syntax. It is:
- **Indexed** — if you add a GIN index on the tags column later, this query uses it
- **Exact** — matches the full tag string, not a substring
- **Safe** — no SQL injection risk, SQLAlchemy parameterises the value

Compare with the naive approach:
```sql
WHERE tags::text LIKE '%debugging%'
```
This would match `"debugging"` but also accidentally match `"nodebugging"` or any tag that contains `"debugging"` as a substring. The ARRAY approach is exact and correct.

#### `is_public` filter with `None` as "all"

```python
if is_public is not None:
    query = query.filter(JournalEntry.is_public == is_public)
```

`None` means no filter — return all entries regardless of visibility. `True` means only public entries. `False` means only private entries. The three values map to three distinct behaviours with one parameter.

This is the same `None` as no-op pattern used in Phase 3's status filter.

#### `order_by(JournalEntry.updated_at.desc())`

Most recently updated entries first. For a journal, this makes the most sense — the entry you were just editing should surface at the top. For coding sessions, `session_date.desc()` was used — the most recently coded session first.

---

### `update_entry`

```python
def update_entry(
    entry_id: int, data: JournalUpdate, user: User, db: Session
) -> JournalEntry:
    entry = _get_entry_or_404(entry_id, user.id, db)

    update_data = data.model_dump(exclude_unset=True)

    if "tags" in update_data and update_data["tags"] is not None:
        update_data["tags"] = list(
            dict.fromkeys(t.strip().lower() for t in update_data["tags"] if t.strip())
        )

    for field, value in update_data.items():
        setattr(entry, field, value)

    db.commit()
    db.refresh(entry)
    return entry
```

#### Why tags are cleaned again in the service

`JournalCreate` has a `clean_tags` validator that runs on create. `JournalUpdate` is a different schema — its `tags` field has no validator because `JournalUpdate` fields are all optional and validators on optional fields can interfere with the `exclude_unset` mechanism.

So the service re-applies the same cleaning logic on update:

```python
list(dict.fromkeys(t.strip().lower() for t in update_data["tags"] if t.strip()))
```

Breaking this down:
- `t.strip().lower()` — strip whitespace and lowercase each tag
- `if t.strip()` — filter out blank strings
- `dict.fromkeys(...)` — deduplicate while preserving insertion order (a dict can't have duplicate keys)
- `list(...)` — convert back to a list

Without this, a client could `PATCH` with `{"tags": ["React", "REACT", "react"]}` and store three identical tags. The cleaning produces `["react"]`.

#### When to clean in schema vs service

A good rule: validation logic that **rejects** bad data belongs in the schema (raise `ValueError`). Transformation logic that **normalises** data can live in the schema, but must also be repeated in the service for any update path that bypasses the create schema's validators.

---

### `delete_entry`

```python
def delete_entry(entry_id: int, user: User, db: Session) -> dict:
    entry = _get_entry_or_404(entry_id, user.id, db)
    title = entry.title
    db.delete(entry)
    db.commit()
    return {"message": f"Journal entry '{title}' deleted successfully"}
```

**`title = entry.title` before the delete** — the same pattern from Phase 3's `delete_project`. After `db.commit()`, the deleted object is in a detached, potentially unusable state. The title is captured before the commit so it can be included in the success message safely.

---

## 7. `routers/journal.py`

```python
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import Optional

from app.core.deps import get_db, get_current_user
from app.models.users import User
from app.schemas.journal import JournalCreate, JournalUpdate, JournalResponse
from app.services import journal_service

router = APIRouter(prefix="/journal", tags=["journal"])
```

---

### `create_entry` route

```python
@router.post("", status_code=201, response_model=JournalResponse)
def create_entry(
    data: JournalCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return journal_service.create_entry(data, current_user, db)
```

`JournalCreate` validators run before this handler:
- `title_not_empty` — rejects blank titles
- `body_not_empty` — rejects blank bodies
- `clean_tags` — lowercases, strips, and deduplicates tags

If any validator raises, `422` is returned. The service receives clean, validated data.

---

### `list_entries` route

```python
@router.get("", response_model=list[JournalResponse])
def list_entries(
    tag:       Optional[str]  = Query(default=None, description="Filter by tag"),
    is_public: Optional[bool] = Query(default=None, description="True = public only, False = private only"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return journal_service.list_entries(current_user, db, tag=tag, is_public=is_public)
```

Two optional query parameters. Example URL combinations:

```
GET /api/journal                        → all entries
GET /api/journal?tag=debugging          → entries tagged "debugging"
GET /api/journal?is_public=true         → only public entries
GET /api/journal?tag=fastapi&is_public=false  → private entries tagged "fastapi"
```

**`Optional[bool]` with `Query`** — FastAPI parses `"true"` and `"false"` strings from the URL into Python `bool`. `?is_public=true` becomes `True`, `?is_public=false` becomes `False`. This is automatic — no manual string comparison needed.

---

### `update_entry` route

```python
@router.patch("/{entry_id}", response_model=JournalResponse)
def update_entry(
    entry_id: int,
    data: JournalUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return journal_service.update_entry(entry_id, data, current_user, db)
```

`JournalUpdate` has all optional fields — any subset can be sent. Common use cases:
- Toggle visibility: `{"is_public": true}`
- Add tags: `{"tags": ["debugging", "performance"]}`
- Edit content: `{"body": "updated body text"}`
- Any combination of the above

The `exclude_unset=True` in the service ensures only sent fields are updated.

---

## 8. `main.py` — Updated

```python
import app.models  # noqa: F401

from app.routers import auth, projects, tasks, sessions, journal

app.include_router(auth.router,     prefix="/api")
app.include_router(projects.router, prefix="/api")
app.include_router(tasks.router,    prefix="/api")
app.include_router(sessions.router, prefix="/api")
app.include_router(journal.router,  prefix="/api")
```

Two new imports and two new `include_router` calls. The `/api` prefix is applied to all routers — the individual router prefixes (`/sessions`, `/journal`) stack on top.

**Final URL structure across all phases:**

```
/api/auth/...                    ← Phase 1
/api/projects/...                ← Phase 3
/api/projects/{id}/tasks/...     ← Phase 3
/api/sessions/...                ← Phase 4
/api/journal/...                 ← Phase 4
```

---

## 9. Request Lifecycle Walkthroughs

### Logging a session linked to a project

```
POST /api/sessions
Cookie: access_token=eyJ...
Body: {"duration_mins": 90, "session_date": "2026-03-23", "project_id": 1}

1. FastAPI routes to create_session() in routers/sessions.py

2. Depends(get_current_user):
   → reads access_token cookie
   → decodes JWT, extracts user_id=3
   → SELECT * FROM users WHERE id = 3 → User(id=3)

3. Body parsed against SessionCreate:
   → duration_mins=90: validator checks 0 < 90 <= 1440 → passes
   → session_date="2026-03-23": Pydantic parses to date(2026, 3, 23) → passes
   → project_id=1: Optional[int], no special validation at schema level

4. session_service.create_session(data, user, db):

   a. data.project_id is not None (it's 1) → run _validate_project_ownership(1, 3, db)
      → SELECT * FROM projects WHERE id = 1 → found
      → project.user_id (3) == user.id (3) → OK, returns None

   b. CodingSession object constructed:
      user_id=3, project_id=1, duration_mins=90,
      session_date=date(2026, 3, 23), notes=None

   c. db.add(session) → staged
   d. db.commit() → INSERT INTO coding_sessions ... executed
   e. db.refresh(session) → id and created_at populated from DB
   f. session returned

5. FastAPI serialises through SessionResponse
6. HTTP 201 returned with the new session object
```

---

### Getting a weekly summary

```
GET /api/sessions/summary?date_from=2026-03-17&date_to=2026-03-23
Cookie: access_token=eyJ...

1. FastAPI routes — "/summary" matched BEFORE "/{session_id}" because it's declared first
   → If declared in wrong order: "summary" treated as session_id → 422

2. Depends(get_current_user) → User(id=3)

3. Query params parsed:
   → date_from="2026-03-17" → date(2026, 3, 17)
   → date_to="2026-03-23" → date(2026, 3, 23)

4. session_service.get_summary(user, db, date_from, date_to):

   a. Totals query executed:
      SELECT SUM(duration_mins), COUNT(id)
      FROM coding_sessions
      WHERE user_id = 3
        AND session_date >= '2026-03-17'
        AND session_date <= '2026-03-23'
      → one row returned: (total_mins=420, total_sessions=4)

   b. Per-project query executed:
      SELECT project_id, SUM(duration_mins), COUNT(id)
      FROM coding_sessions
      WHERE user_id = 3
        AND session_date >= '2026-03-17'
        AND session_date <= '2026-03-23'
      GROUP BY project_id
      → two rows: (project_id=1, mins=270, sessions=3), (project_id=None, mins=150, sessions=1)

   c. Return dict constructed:
      total_mins=420, total_hours=7.0, total_sessions=4,
      per_project=[{project_id: 1, ...}, {project_id: null, ...}]

5. FastAPI serialises plain dict → JSON response
HTTP 200
{
  "total_mins": 420,
  "total_hours": 7.0,
  "total_sessions": 4,
  "per_project": [
    {"project_id": 1, "total_mins": 270, "total_sessions": 3},
    {"project_id": null, "total_mins": 150, "total_sessions": 1}
  ]
}
```

---

### Filtering journal entries by tag

```
GET /api/journal?tag=debugging
Cookie: access_token=eyJ...

1. FastAPI routes to list_entries() in routers/journal.py
2. Depends(get_current_user) → User(id=3)
3. tag="debugging" extracted from query params

4. journal_service.list_entries(user, db, tag="debugging", is_public=None):

   a. Base query: SELECT * FROM journal_entries WHERE user_id = 3
   b. tag is not None: add .filter(tags.contains(["debugging"]))
      → WHERE 'debugging' = ANY(tags)
   c. is_public is None: no visibility filter added
   d. ORDER BY updated_at DESC

   Generated SQL:
   SELECT * FROM journal_entries
   WHERE user_id = 3 AND 'debugging' = ANY(tags)
   ORDER BY updated_at DESC

5. Matching entries returned, serialised through list[JournalResponse]
HTTP 200
[
  {"id": 1, "title": "Debugging the cascade delete", "tags": ["debugging", "sqlalchemy"], ...},
  ...
]
```

---

### Updating journal entry tags with automatic normalisation

```
PATCH /api/journal/1
Cookie: access_token=eyJ...
Body: {"tags": ["React", "REACT", "  fastapi  ", ""]}

1. FastAPI routes to update_entry()
2. get_current_user → User(id=3)
3. Body parsed against JournalUpdate → {"tags": ["React", "REACT", "  fastapi  ", ""]}
   (JournalUpdate has no tag validator — all fields optional, no cleaning here)

4. journal_service.update_entry(1, data, user, db):

   a. _get_entry_or_404(1, 3, db) → entry found, owned by user 3

   b. update_data = data.model_dump(exclude_unset=True)
      → {"tags": ["React", "REACT", "  fastapi  ", ""]}

   c. "tags" in update_data and not None → run tag cleaning:
      - "React".strip().lower() = "react" (kept, not blank)
      - "REACT".strip().lower() = "react" (duplicate — removed by dict.fromkeys)
      - "  fastapi  ".strip().lower() = "fastapi" (kept)
      - "".strip() = "" → if t.strip() is falsy → filtered out
      → update_data["tags"] = ["react", "fastapi"]

   d. setattr(entry, "tags", ["react", "fastapi"])
   e. db.commit() → UPDATE journal_entries SET tags='{react,fastapi}', updated_at=NOW()
   f. db.refresh(entry)

5. JournalResponse serialised
HTTP 200
{"id": 1, "tags": ["react", "fastapi"], "updated_at": "2026-03-23T...", ...}
```

---

## 10. Verification & Manual Testing

Start the server and go to `http://localhost:8000/docs`.

### Sessions

**1. Log a session with no project:**
```json
POST /api/sessions
{"duration_mins": 60, "session_date": "2026-03-23", "notes": "Read FastAPI docs"}
```
Expected: `201`, `project_id` is `null`.

**2. Log a session linked to a project** (use a project ID you created in Phase 3):
```json
POST /api/sessions
{"duration_mins": 120, "session_date": "2026-03-22", "project_id": 1}
```
Expected: `201`, `project_id: 1`.

**3. Try linking to a project you don't own:**
```json
POST /api/sessions
{"duration_mins": 30, "session_date": "2026-03-23", "project_id": 9999}
```
Expected: `404` — project doesn't exist.

**4. Test date filtering:**
```
GET /api/sessions?date_from=2026-03-22&date_to=2026-03-22
```
Expected: only the session from March 22nd.

**5. Test the summary** — critically, test route ordering:
```
GET /api/sessions/summary
```
Expected: a summary dict, **not** a `422` about `"summary"` being an invalid integer. If you get `422`, `/summary` is declared after `/{session_id}` in your router.

**6. Get the summary with a date range:**
```
GET /api/sessions/summary?date_from=2026-03-01&date_to=2026-03-31
```
Expected: `total_mins: 180`, `total_hours: 3.0`, `total_sessions: 2`, `per_project` with one entry for project 1 and one for `null`.

**7. Update a session:**
```json
PATCH /api/sessions/1
{"notes": "Read FastAPI docs — finished the routing chapter"}
```
Expected: only the `notes` field changes. `duration_mins` and `session_date` are unchanged.

---

### Journal

**8. Create a private entry:**
```json
POST /api/journal
{
  "title": "Why I store time in minutes",
  "body": "Floating point arithmetic causes drift when summing...",
  "tags": ["Architecture", "ARCHITECTURE", "  design  ", ""],
  "is_public": false
}
```
Expected: `201`. Check `tags` — must be `["architecture", "design"]`. The duplicate `"Architecture"/"ARCHITECTURE"` collapses to one, the blank string is removed, both are lowercased.

**9. Create a public entry:**
```json
POST /api/journal
{
  "title": "FastAPI vs Django — my take",
  "body": "After building DevPulse with FastAPI...",
  "tags": ["fastapi", "python"],
  "is_public": true
}
```

**10. Filter by tag:**
```
GET /api/journal?tag=architecture
GET /api/journal?tag=fastapi
```
Expected: first returns only entry 1, second returns only entry 2.

**11. Filter by visibility:**
```
GET /api/journal?is_public=false
GET /api/journal?is_public=true
GET /api/journal
```
Expected: one entry each for the first two, both entries for the third.

**12. Test PATCH with tag normalisation:**
```json
PATCH /api/journal/1
{"tags": ["Architecture", "ARCHITECTURE", "debugging"]}
```
Expected: `tags: ["architecture", "debugging"]` — deduplicated and lowercased.

**13. Toggle visibility:**
```json
PATCH /api/journal/1
{"is_public": true}
```
Expected: only `is_public` changes. `title`, `body`, `tags` are unchanged.

**14. Delete an entry:**
```
DELETE /api/journal/2
```
Expected: `200` with success message. `GET /api/journal/2` should return `404`.

---

## 11. Design Decisions Summary

| Decision | Reasoning |
|---|---|
| Sessions are flat (`/api/sessions`), not nested under projects | Sessions have an optional project link — nesting would make project-less sessions impossible to express |
| `/summary` declared before `/{session_id}` in router | FastAPI matches routes in declaration order — literal paths must precede parameterised ones sharing a prefix |
| `_validate_project_ownership` as a separate helper | Optional FK validation follows the same ownership pattern as required FKs — prevents users from linking sessions to other users' projects |
| `func.sum()` and `func.count()` instead of Python loops | SQL aggregation runs inside the database — one row returned instead of N rows fetched and summed in Python |
| `.label("total_mins")` on aggregated columns | Named access (`result.total_mins`) instead of fragile positional access (`result[0]`) |
| `totals.total_mins or 0` | `SUM()` on an empty set returns `NULL` in SQL — `or 0` provides a clean default for users with no sessions in the date range |
| `round(..., 1)` for hours | One decimal place for display — avoids floating point noise like `3.5000000000000004` |
| Tag cleaning applied in both schema and service | Create path: cleaned by `JournalCreate` validator. Update path: no validator on `JournalUpdate`, so service re-applies the same logic — ensures consistency regardless of code path |
| `JournalEntry.tags.contains([tag.lower()])` for tag filter | Native PostgreSQL `= ANY(array)` — exact match, indexed, no substring false positives from `LIKE` |
| `is_public: None = all, True = public, False = private` | Three behaviours from one optional parameter — `None` as the no-op value is the standard pattern for optional filters |
| `title = entry.title` captured before delete commit | Deleted objects are detached after commit — capture any needed values before the commit runs |
| `order_by(updated_at.desc())` on journal entries | Most recently edited entries surface first — natural for a writing tool |
| `order_by(session_date.desc())` on sessions | Most recently coded sessions first — natural for a log/timeline view |

---

*Next: Phase 5 — Public Profile Endpoint*
