# DevPulse — Phase 2 Documentation
## Core Data Models & Schemas

> **Stack:** FastAPI · SQLAlchemy ORM · PostgreSQL · Pydantic v2  
> **Phase goal:** Design and implement the complete data layer — all models, relationships, schemas, and the migration that brings it live.

---

## Table of Contents

1. [Overview](#1-overview)
2. [The Relationship Map](#2-the-relationship-map)
3. [models/project.py](#3-modelsprojectpy)
4. [models/task.py](#4-modelstaskpy)
5. [models/session.py](#5-modelssessionpy)
6. [models/journal.py](#6-modelsjournalpy)
7. [models/users.py — Updated](#7-modelsuserspyupdated)
8. [models/__init__.py — The Critical Fix](#8-models__init__py--the-critical-fix)
9. [schemas/project.py](#9-schemasprojectpy)
10. [schemas/task.py](#10-schemastaskpy)
11. [schemas/session.py](#11-schemassessionpy)
12. [schemas/journal.py](#12-schemasjournalpy)
13. [db/init_db.py — Updated](#13-dbinit_dbpy--updated)
14. [Alembic Migrations](#14-alembic-migrations)
15. [Verification Checklist](#15-verification-checklist)
16. [Design Decisions Summary](#16-design-decisions-summary)

---

## 1. Overview

Phase 1 gave you authentication — a user can register, log in, and get a session. But after logging in, there was nothing to actually do. Phase 2 builds the **entire data layer** that makes DevPulse a real product.

Four new models are introduced:

| Model | Table | What it represents |
|---|---|---|
| `Project` | `projects` | A software project a developer is working on |
| `Task` | `tasks` | A unit of work within a project |
| `CodingSession` | `coding_sessions` | A logged block of coding time |
| `JournalEntry` | `journal_entries` | A developer's written reflection or learning |

Each model follows the same structure:
- A **SQLAlchemy model** (`models/`) defines the database table
- A **Pydantic schema** (`schemas/`) defines what data looks like going in and coming out of the API

No routes are written yet. Phase 2 is purely the foundation. Getting the schema right now prevents painful database migrations later.

---

## 2. The Relationship Map

Before reading any model file, understand how they connect. This prevents you from putting foreign keys in the wrong direction.

```
User
├── projects[]        (one User → many Projects)
│   └── tasks[]       (one Project → many Tasks)
│   └── sessions[]    (one Project → many CodingSessions, optional)
├── sessions[]        (one User → many CodingSessions directly)
└── journal_entries[] (one User → many JournalEntries)
```

**Three rules that come from this map:**

1. `Task` has no direct `user_id`. You reach its owner through `task → project → user`. Adding a direct `user_id` on `Task` would be denormalization — it creates the risk of a task's `user_id` not matching its project's `user_id`.

2. `CodingSession` has **two** foreign keys — `user_id` (required) and `project_id` (optional). A session always belongs to a user. It may or may not be tied to a specific project.

3. `JournalEntry` belongs directly to `User`, not to any project. Writing is freeform — forcing it into a project context limits the tool.

---

## 3. `models/project.py`

```python
import enum
from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, String, DateTime,
    Boolean, Enum as SAEnum, ForeignKey, Text
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import relationship
from app.db.base import Base


class ProjectStatus(str, enum.Enum):
    planning    = "planning"
    in_progress = "in_progress"
    completed   = "completed"
    on_hold     = "on_hold"


class Project(Base):
    __tablename__ = "projects"

    id          = Column(Integer, primary_key=True, index=True)
    user_id     = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title       = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    status      = Column(SAEnum(ProjectStatus), nullable=False, default=ProjectStatus.planning)
    tech_stack  = Column(ARRAY(String), nullable=False, default=list)
    github_url  = Column(String(500), nullable=True)
    live_url    = Column(String(500), nullable=True)
    is_public   = Column(Boolean, nullable=False, default=False)
    created_at  = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at  = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                         onupdate=lambda: datetime.now(timezone.utc))

    owner    = relationship("User", back_populates="projects")
    tasks    = relationship("Task", back_populates="project", cascade="all, delete-orphan")
    sessions = relationship("CodingSession", back_populates="project")
```

### Line-by-line breakdown

---

#### `class ProjectStatus(str, enum.Enum)`

Defines a restricted set of valid status values. Inheriting from both `str` and `enum.Enum` does two things:

- **`str`** — values serialize to plain strings (`"planning"`) automatically in JSON. Without it, FastAPI would try to serialize `<ProjectStatus.planning: 'planning'>` and fail.
- **`enum.Enum`** — restricts the column to only these four values. The database enforces this constraint independently of your Python code.

---

#### `Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)`

- `ForeignKey("users.id")` — links every project to a user. The string `"users.id"` refers to the `id` column in the `users` table.
- `ondelete="CASCADE"` — when a user is deleted from the database, all their projects are deleted automatically by the database engine. This is a **database-level** cascade.
- `nullable=False` — every project must have an owner. A project without a user cannot exist.
- `index=True` — creates a database index on this column. Since you'll constantly query `WHERE user_id = ?` to fetch a user's projects, an index makes this dramatically faster.

---

#### `Column(String(200), nullable=False)` on `title`

`String(200)` sets a maximum length of 200 characters at the database level. The database will reject any value longer than this. Compare to `String` (no argument) which is unlimited. Use length limits on user-facing string fields to prevent abuse.

---

#### `Column(Text, nullable=True)` on `description`

`Text` vs `String` — `String` maps to `VARCHAR` in PostgreSQL (fixed max length). `Text` maps to PostgreSQL's `TEXT` type — unlimited length, no ceiling. Use `Text` for fields where content can be long and unpredictable: descriptions, notes, journal bodies.

---

#### `Column(ARRAY(String), nullable=False, default=list)`

This is a PostgreSQL-native array column. It stores `["React", "FastAPI", "PostgreSQL"]` as a real array, not a comma-separated string.

**Why not store as a string like `"React,FastAPI,PostgreSQL"`?**

Because you'd lose the ability to query cleanly. With `ARRAY`, you can later do:
```sql
SELECT * FROM projects WHERE 'React' = ANY(tech_stack);
```

With a string, you'd have to do:
```sql
SELECT * FROM projects WHERE tech_stack LIKE '%React%';
```

The `LIKE` approach is slow, fragile, and breaks if a tag name is a substring of another tag. Use native arrays.

**`default=list`** — passes the `list` constructor as the factory function. SQLAlchemy calls `list()` for each new row, producing a fresh empty list `[]`. If you wrote `default=[]`, that same list object would be shared across all rows — a classic Python mutable default bug.

---

#### `Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))`

- **`default=lambda:`** — the `lambda` wrapper evaluates `datetime.now()` freshly for each row insert. Without it, the expression is evaluated once at class definition time and every row would share the same timestamp.
- **`onupdate=lambda:`** — fires automatically every time SQLAlchemy flushes a change to this row. You never have to manually set `updated_at = datetime.now()` in your service code. SQLAlchemy handles it.

---

#### `relationship("Task", back_populates="project", cascade="all, delete-orphan")`

- `back_populates="project"` — the other side of this relationship is the `project` attribute on `Task`. Both sides must declare `back_populates` pointing to each other. This makes both sides of the relationship navigable.
- `cascade="all, delete-orphan"` — when a project is deleted in Python (through SQLAlchemy), all its tasks are deleted too. `delete-orphan` extends this to also delete tasks that are removed from `project.tasks` without the project itself being deleted.

**Difference between `ondelete="CASCADE"` (on the FK) and `cascade="all, delete-orphan"` (on the relationship):**

| | Fires when |
|---|---|
| `ondelete="CASCADE"` | You delete via raw SQL or the database directly |
| `cascade="all, delete-orphan"` | You delete via SQLAlchemy's Python ORM |

Having both covers all scenarios.

---

#### `relationship("CodingSession", back_populates="project")` — no cascade

Sessions deliberately have **no cascade**. If you delete a project, sessions that were linked to it should not disappear — they are historical records of time spent. Instead, the `project_id` on the session becomes `NULL` (handled by `ondelete="SET NULL"` on the session model's FK). The session still exists and still counts toward total coding hours.

---

## 4. `models/task.py`

```python
import enum
from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, String, DateTime,
    Boolean, Enum as SAEnum, ForeignKey, Text
)
from sqlalchemy.orm import relationship
from app.db.base import Base


class TaskStatus(str, enum.Enum):
    todo        = "todo"
    in_progress = "in_progress"
    done        = "done"


class TaskPriority(str, enum.Enum):
    low    = "low"
    medium = "medium"
    high   = "high"


class Task(Base):
    __tablename__ = "tasks"

    id           = Column(Integer, primary_key=True, index=True)
    project_id   = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    title        = Column(String(300), nullable=False)
    description  = Column(Text, nullable=True)
    status       = Column(SAEnum(TaskStatus), nullable=False, default=TaskStatus.todo)
    priority     = Column(SAEnum(TaskPriority), nullable=False, default=TaskPriority.medium)
    time_logged  = Column(Integer, nullable=False, default=0)
    completed_at = Column(DateTime, nullable=True)
    created_at   = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at   = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                          onupdate=lambda: datetime.now(timezone.utc))

    project = relationship("Project", back_populates="tasks")
```

### Line-by-line breakdown

---

#### `ForeignKey("projects.id", ondelete="CASCADE")`

Tasks belong to projects, not users. The cascade means: delete a project → all its tasks are automatically deleted. You never end up with orphaned tasks pointing to a non-existent project.

**No `user_id` on Task** — you reach the owner by navigating `task.project.user_id`. Storing `user_id` directly on `Task` would create a redundancy that can fall out of sync. If a task's `user_id` ever differed from its project's `user_id`, your data would be corrupted.

---

#### `time_logged = Column(Integer, nullable=False, default=0)`

Stores time in **minutes as an integer**. Never use a float for time values.

**Why not float?** Floating point arithmetic is imprecise. `0.1 + 0.2` in Python is `0.30000000000000004`. Summing dozens of float hours produces drift. With integers and minutes:

```python
total_hours = total_minutes // 60    # integer division — exact
leftover    = total_minutes % 60     # modulo — exact
```

`SUM(time_logged)` across thousands of rows gives a perfectly accurate result.

---

#### `completed_at = Column(DateTime, nullable=True)`

`None` means the task is not done. When the service transitions a task to `status = done`, it sets `completed_at = datetime.now(timezone.utc)` simultaneously.

**Why not just use `status`?** Status is a category. `completed_at` is a precise timestamp. With this column you can compute:
- Average time from task creation to completion
- Tasks completed per week
- Time a task spent in `in_progress` state

None of these are possible from a status string alone.

---

## 5. `models/session.py`

```python
from datetime import datetime, date, timezone
from sqlalchemy import (
    Column, Integer, String, DateTime,
    Date, ForeignKey, Text
)
from sqlalchemy.orm import relationship
from app.db.base import Base


class CodingSession(Base):
    __tablename__ = "coding_sessions"

    id             = Column(Integer, primary_key=True, index=True)
    user_id        = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id     = Column(Integer, ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True)
    duration_mins  = Column(Integer, nullable=False)
    session_date   = Column(Date, nullable=False, index=True)
    notes          = Column(Text, nullable=True)
    created_at     = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    owner   = relationship("User", back_populates="sessions")
    project = relationship("Project", back_populates="sessions")
```

### Line-by-line breakdown

---

#### Two foreign keys — `user_id` required, `project_id` optional

Every session must belong to a user (`nullable=False`). Sessions may optionally be linked to a project (`nullable=True`). This models real developer behaviour — sometimes you code for a specific project, sometimes you do general learning or exploration with no project context.

---

#### `ForeignKey("projects.id", ondelete="SET NULL")`

`SET NULL` is different from `CASCADE`. When the referenced project is deleted:
- `CASCADE` would delete the session too — **wrong**, you lose history
- `SET NULL` sets `project_id = NULL` on the session — **correct**, the session still exists, still counts toward total hours, just loses its project link

This is the only FK in the project that uses `SET NULL` instead of `CASCADE`.

---

#### `session_date = Column(Date, nullable=False, index=True)`

`Date` stores only year/month/day — no time component. This is a deliberate design choice for analytics.

**Why not just use `created_at`?**

Developers log sessions after the fact. If you code at 10pm and log it the next morning, `created_at` would be tomorrow but the session happened today. `session_date` is the calendar date the developer explicitly says they coded — it's user-controlled.

**Why index `session_date`?**

Your most common analytics queries will be:
```sql
SELECT SUM(duration_mins) FROM coding_sessions
WHERE user_id = ? AND session_date >= ?;
```

Without an index on `session_date`, this is a full table scan across all rows. With the index, PostgreSQL goes directly to the matching date range.

---

#### `duration_mins` — no `start_time`/`end_time`

You could store start and end timestamps and compute `duration = end - start`. But that design assumes a live timer — users click start, work, click stop. DevPulse's primary use case is retrospective logging ("I coded for 90 minutes today"). A simple integer is the right fit. You can always add a timer feature later as a separate column.

---

## 6. `models/journal.py`

```python
from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, String, DateTime,
    Boolean, ForeignKey, Text
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import relationship
from app.db.base import Base


class JournalEntry(Base):
    __tablename__ = "journal_entries"

    id         = Column(Integer, primary_key=True, index=True)
    user_id    = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title      = Column(String(300), nullable=False)
    body       = Column(Text, nullable=False)
    tags       = Column(ARRAY(String), nullable=False, default=list)
    is_public  = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    author = relationship("User", back_populates="journal_entries")
```

### Line-by-line breakdown

---

#### No `project_id` FK

Journal entries are not attached to projects. Writing is freeform — a developer writes about whatever they experienced, learned, or figured out. Forcing entries into a project context would break the use case where someone writes about a general concept, a book they read, or a problem unrelated to any current project.

If you want filtered views like "journal entries related to this project" in the future, that's a feature to add later — not a constraint to bake in now.

---

#### `tags = Column(ARRAY(String), nullable=False, default=list)`

Same reasoning as `tech_stack` on `Project`. Tags like `["debugging", "learning", "architecture"]` stored as a real PostgreSQL array allow clean queries:

```sql
SELECT * FROM journal_entries
WHERE is_public = true AND 'debugging' = ANY(tags);
```

---

#### `is_public = Column(Boolean, nullable=False, default=False)`

The toggle that controls what appears on the public portfolio page. Defaults to `False` — entries are private unless explicitly published. This gives developers full control over their public image. The public profile endpoint will filter on `WHERE is_public = true`.

---

#### `body = Column(Text, nullable=False)`

`nullable=False` because a journal entry without a body is meaningless. A title with no content is not a journal entry. The schema validator (`JournalCreate`) also enforces this at the API layer, but having it `nullable=False` at the DB level means the constraint exists even if the validator is bypassed.

---

## 7. `models/users.py` — Updated

The `User` model needs the reverse sides of all four new relationships. Without these, you can't navigate from a user to their projects, sessions, or journal entries.

```python
import enum
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, Boolean, Enum as SAEnum
from sqlalchemy.orm import relationship
from app.db.base import Base


class UserRole(str, enum.Enum):
    admin     = "admin"
    developer = "developer"


class User(Base):
    __tablename__ = "users"

    id            = Column(Integer, primary_key=True, index=True)
    name          = Column(String, nullable=False)
    email         = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    role          = Column(SAEnum(UserRole), nullable=False, default=UserRole.developer)
    is_verified   = Column(Boolean, nullable=False, default=False)
    totp_secret   = Column(String, nullable=True, default=None)
    created_at    = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    projects        = relationship("Project",       back_populates="owner",  cascade="all, delete-orphan")
    sessions        = relationship("CodingSession", back_populates="owner",  cascade="all, delete-orphan")
    journal_entries = relationship("JournalEntry",  back_populates="author", cascade="all, delete-orphan")
```

### Line-by-line breakdown

---

#### `back_populates` vs `backref` — why we use `back_populates`

Both approaches wire up the reverse side of a relationship. The difference is visibility:

| | Where both sides are declared |
|---|---|
| `back_populates` | **Both files** — `users.py` has `projects`, `project.py` has `owner` |
| `backref` | **One file only** — the other side is magically created, invisible in its own file |

`back_populates` is preferred because you can open either model file and immediately see every relationship it participates in. With `backref`, half the relationship is invisible in one of the two files — a source of confusion when the codebase grows.

---

#### `cascade="all, delete-orphan"` on all three relationships

When a user account is deleted, everything they own should be cleaned up:
- Their projects (which cascade to their tasks)
- Their sessions
- Their journal entries

The cascade chain is: `delete User → delete Projects, Sessions, JournalEntries → delete Tasks (via Project cascade)`.

Without this, deleting a user would fail with a foreign key constraint error because child rows still reference them.

---

#### Relationship naming is intentional

| Attribute | Named | Why |
|---|---|---|
| `projects` | owner → project | owner reads naturally: `user.projects` |
| `sessions` | owner → session | same |
| `journal_entries` | author → journal | a person *authors* a journal, not *owns* it |

Naming relationships after the real-world role makes code read like English: `user.journal_entries`, `entry.author`.

---

## 8. `models/__init__.py` — The Critical Fix

```python
# app/models/__init__.py

from app.models.users import User, UserRole       # noqa: F401
from app.models.token import RefreshToken         # noqa: F401
from app.models.project import Project            # noqa: F401
from app.models.task import Task                  # noqa: F401
from app.models.session import CodingSession      # noqa: F401
from app.models.journal import JournalEntry       # noqa: F401
```

### Why this file exists

SQLAlchemy uses a string-based registry for lazy relationship resolution. When you write `relationship("Project")` in `users.py`, SQLAlchemy stores the string `"Project"` and resolves it to the actual Python class when the mapper initializes.

**That resolution only works if `Project` has already been imported.**

Without `__init__.py`, the import order is unpredictable. If `users.py` is imported first — which it always is because it's referenced by `auth_service.py`, `deps.py`, and `auth.py` — SQLAlchemy tries to resolve `"Project"` before `project.py` has been imported. Nothing is registered under that name yet. The error thrown:

```
sqlalchemy.exc.InvalidRequestError: When initializing mapper Mapper[User(users)],
expression 'Project' failed to locate a name ('Project').
```

`__init__.py` solves this by loading all six models together in a single, predictable import. By the time SQLAlchemy initializes any mapper, all classes are registered.

---

#### How to trigger it in `main.py`

```python
import app.models  # noqa: F401
```

This one line runs `__init__.py`, which imports all models. Place it **before** any router imports in `main.py`.

---

#### `# noqa: F401` — what this comment means

`F401` is a linting rule: "imported but unused". Your linter (flake8 or ruff) would flag every line in `__init__.py` as a violation because the imported names are never explicitly used in code.

`# noqa: F401` tells the linter to suppress that warning for that line. These imports exist for their **side effect** — registering classes with SQLAlchemy's mapper registry — not because they're called directly. The comment is intentional documentation of that fact, not a workaround.

---

## 9. `schemas/project.py`

```python
from pydantic import BaseModel, field_validator
from datetime import datetime
from typing import Optional
from app.models.project import ProjectStatus


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
        cleaned = list(dict.fromkeys(tag.strip() for tag in v if tag.strip()))
        return cleaned


class ProjectUpdate(BaseModel):
    title:       Optional[str]           = None
    description: Optional[str]           = None
    status:      Optional[ProjectStatus] = None
    tech_stack:  Optional[list[str]]     = None
    github_url:  Optional[str]           = None
    live_url:    Optional[str]           = None
    is_public:   Optional[bool]          = None


class ProjectResponse(BaseModel):
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
```

### The three-shape pattern

Every feature in this project follows a three-schema pattern:

| Schema | Purpose | Fields |
|---|---|---|
| `XCreate` | What the client sends when creating | Required fields + optional with defaults |
| `XUpdate` | What the client sends when editing | All fields optional (`Optional[T] = None`) |
| `XResponse` | What the API sends back | All fields, including DB-generated ones (`id`, `created_at`) |

---

### `ProjectCreate` breakdown

---

#### `@field_validator("title")`

```python
@field_validator("title")
@classmethod
def title_not_empty(cls, v: str) -> str:
    if not v.strip():
        raise ValueError("Title cannot be blank")
    return v.strip()
```

- `@field_validator("title")` — Pydantic v2 decorator. Runs this function on the `title` field after type checking passes.
- `@classmethod` — required by Pydantic v2. The validator is a class method, receiving `cls` not `self`.
- `v.strip()` — strips leading/trailing whitespace. Without this, a title of `"   "` (spaces only) would pass a simple `if not v` check but is still a blank title.
- `raise ValueError(...)` — Pydantic catches `ValueError` from validators and converts it to a `422 Unprocessable Entity` response with the error detail included in the JSON body.
- `return v.strip()` — validators can transform the value. Returning the stripped version means the title is cleaned before it ever reaches the service or database.

---

#### `@field_validator("tech_stack")`

```python
@classmethod
def clean_tech_stack(cls, v: list[str]) -> list[str]:
    cleaned = list(dict.fromkeys(tag.strip() for tag in v if tag.strip()))
    return cleaned
```

Three things happen in one line:
1. `tag.strip()` — removes whitespace from each tag
2. `if tag.strip()` — filters out blank/empty strings
3. `dict.fromkeys(...)` — deduplicates while preserving insertion order. `{"React": None, "FastAPI": None}` as keys, then `list()` converts back to a list. Using a `set` would also deduplicate but loses order.

The result: `["React", "  react ", "FastAPI", ""]` becomes `["React", "FastAPI"]`.

---

### `ProjectUpdate` — all fields Optional

```python
class ProjectUpdate(BaseModel):
    title:  Optional[str] = None
    status: Optional[ProjectStatus] = None
    # ...
```

Every field is `Optional[T] = None`. This means the client only sends what they want to change. A PATCH request to update just the status sends `{"status": "completed"}` — no other fields required.

In the service layer, you'll apply only the fields that are not `None`:

```python
# In project_service.py (Phase 3)
update_data = data.model_dump(exclude_unset=True)
for field, value in update_data.items():
    setattr(project, field, value)
```

`exclude_unset=True` is key — it only includes fields the client actually sent, not fields that defaulted to `None`.

---

### `model_config = {"from_attributes": True}`

This replaces Pydantic v1's `class Config: orm_mode = True`.

It tells Pydantic to read values from SQLAlchemy model attributes rather than from a dictionary. Without this, `ProjectResponse.model_validate(db_project)` would fail because Pydantic can't read `db_project.title` — it expects `db_project["title"]`.

**Every `Response` schema needs this.** Create and Update schemas don't — they receive plain dictionaries from the request body.

---

## 10. `schemas/task.py`

```python
from pydantic import BaseModel, field_validator
from datetime import datetime
from typing import Optional
from app.models.task import TaskStatus, TaskPriority


class TaskCreate(BaseModel):
    title:       str
    description: Optional[str]  = None
    status:      TaskStatus     = TaskStatus.todo
    priority:    TaskPriority   = TaskPriority.medium

    @field_validator("title")
    @classmethod
    def title_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Title cannot be blank")
        return v.strip()


class TaskUpdate(BaseModel):
    title:       Optional[str]          = None
    description: Optional[str]          = None
    status:      Optional[TaskStatus]   = None
    priority:    Optional[TaskPriority] = None


class TaskLogTime(BaseModel):
    minutes: int

    @field_validator("minutes")
    @classmethod
    def minutes_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("Minutes must be a positive number")
        return v


class TaskResponse(BaseModel):
    id:           int
    project_id:   int
    title:        str
    description:  Optional[str]
    status:       TaskStatus
    priority:     TaskPriority
    time_logged:  int
    completed_at: Optional[datetime]
    created_at:   datetime
    updated_at:   datetime

    model_config = {"from_attributes": True}
```

### `TaskLogTime` — a dedicated schema for a specific action

```python
class TaskLogTime(BaseModel):
    minutes: int
```

This is a **single-purpose schema** for the "log time on a task" operation. It only carries one field because that's all the operation needs.

The alternative would be to reuse `TaskUpdate` and set `time_logged` in an update. But there's a subtle difference:

- `TaskUpdate` **sets** `time_logged` to a value — potentially overwriting existing time
- `TaskLogTime` should **add** minutes to the existing total — `task.time_logged += minutes`

Having a separate schema makes the intent explicit and prevents accidental overwrites. The route will be `POST /projects/{id}/tasks/{task_id}/log-time` with a `TaskLogTime` body.

---

## 11. `schemas/session.py`

```python
from pydantic import BaseModel, field_validator
from datetime import datetime, date
from typing import Optional


class SessionCreate(BaseModel):
    duration_mins: int
    session_date:  date
    project_id:    Optional[int] = None
    notes:         Optional[str] = None

    @field_validator("duration_mins")
    @classmethod
    def duration_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("Duration must be greater than zero")
        if v > 1440:
            raise ValueError("Duration cannot exceed 1440 minutes (24 hours)")
        return v


class SessionUpdate(BaseModel):
    duration_mins: Optional[int]  = None
    session_date:  Optional[date] = None
    project_id:    Optional[int]  = None
    notes:         Optional[str]  = None


class SessionResponse(BaseModel):
    id:            int
    user_id:       int
    project_id:    Optional[int]
    duration_mins: int
    session_date:  date
    notes:         Optional[str]
    created_at:    datetime

    model_config = {"from_attributes": True}
```

### `duration_mins` validation

```python
if v <= 0:
    raise ValueError("Duration must be greater than zero")
if v > 1440:
    raise ValueError("Duration cannot exceed 1440 minutes (24 hours)")
```

The upper bound of 1440 (24 × 60) is a **data quality guard**. If a user accidentally enters `900` meaning "9 hours" but submits it as minutes (900 minutes = 15 hours), the validator rejects it with a clear error message. Clean data at ingestion means accurate analytics later. Fixing data quality problems after the fact — with hundreds of sessions in the DB — is painful.

---

#### `session_date: date` — Pydantic parses date strings automatically

When the client sends `{"session_date": "2026-03-19"}`, Pydantic automatically parses the ISO 8601 string into a Python `date` object. You write zero parsing code. If the client sends an invalid format, Pydantic returns a `422` automatically.

---

## 12. `schemas/journal.py`

```python
from pydantic import BaseModel, field_validator
from datetime import datetime
from typing import Optional


class JournalCreate(BaseModel):
    title:     str
    body:      str
    tags:      list[str] = []
    is_public: bool      = False

    @field_validator("title")
    @classmethod
    def title_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Title cannot be blank")
        return v.strip()

    @field_validator("body")
    @classmethod
    def body_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Body cannot be blank")
        return v.strip()

    @field_validator("tags")
    @classmethod
    def clean_tags(cls, v: list[str]) -> list[str]:
        return list(dict.fromkeys(tag.strip().lower() for tag in v if tag.strip()))


class JournalUpdate(BaseModel):
    title:     Optional[str]       = None
    body:      Optional[str]       = None
    tags:      Optional[list[str]] = None
    is_public: Optional[bool]      = None


class JournalResponse(BaseModel):
    id:         int
    user_id:    int
    title:      str
    body:       str
    tags:       list[str]
    is_public:  bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class JournalPublicResponse(BaseModel):
    id:         int
    title:      str
    body:       str
    tags:       list[str]
    created_at: datetime

    model_config = {"from_attributes": True}
```

### `clean_tags` — lowercase normalization

```python
return list(dict.fromkeys(tag.strip().lower() for tag in v if tag.strip()))
```

Tags are lowercased during validation. `"React"`, `"REACT"`, and `"react"` all become `"react"`. This normalization runs at write time — every tag in the database is already lowercase. Analytics queries like "how many entries tagged 'react'?" work without case-insensitive gymnastics.

---

### `JournalPublicResponse` — two schemas for one model

```python
class JournalResponse(BaseModel):       # private — full data
    id: int
    user_id: int      # ← includes user_id
    ...

class JournalPublicResponse(BaseModel): # public — stripped
    id: int
                      # ← no user_id
    ...
```

Two schemas for one model. The difference: `JournalPublicResponse` omits `user_id`.

**Why?** The public portfolio endpoint (`GET /users/{id}/profile`) is accessible without authentication. Exposing `user_id` in public responses is an information leak — it exposes your internal database structure. It's a small thing, but it's the right habit. Use the minimal response schema for each context.

The rule is: **never include internal database IDs in public-facing endpoints unless the client specifically needs them for a follow-up request.**

---

## 13. `db/init_db.py` — Updated

```python
from app.db.sessions import engine
from app.db.base import Base

from app.models.users import User               # noqa: F401
from app.models.token import RefreshToken      # noqa: F401
from app.models.project import Project         # noqa: F401
from app.models.task import Task               # noqa: F401
from app.models.session import CodingSession   # noqa: F401
from app.models.journal import JournalEntry    # noqa: F401


def init_db():
    Base.metadata.create_all(bind=engine)
```

Now that Alembic manages your schema, `init_db.py` is kept only as a fallback for local dev environments that don't want to run Alembic. In production, `init_db()` should not be called from `main.py` — schema changes come from `alembic upgrade head` instead.

---

## 14. Alembic Migrations

### What Alembic does

Alembic is the standard migration tool for SQLAlchemy. It tracks schema changes over time exactly the way Git tracks code changes. Every change to your models becomes a migration file with an `upgrade()` and `downgrade()` function.

```
alembic_version table (in your DB)
├── records which migration was last applied
└── used by alembic current, upgrade, downgrade
```

---

### The migration file structure

```python
revision = '1849d5a8a716'      # unique ID for this migration
down_revision = None            # ID of the previous migration (None = first)

def upgrade() -> None:
    # What to do when applying this migration forward
    op.create_table(...)
    op.add_column(...)

def downgrade() -> None:
    # What to undo if rolling back
    op.drop_table(...)
    op.drop_column(...)
```

`down_revision` chains migrations together. Alembic follows the chain to know the order: `None → abc123 → def456 → ...`.

---

### The `server_default` requirement

When adding a `NOT NULL` column to a table that already has rows, PostgreSQL needs a value for those existing rows immediately. `server_default` provides it:

```python
op.add_column('users',
    sa.Column('role',
              sa.Enum('admin', 'developer', name='userrole'),
              nullable=False,
              server_default='developer')   # ← fills existing rows
)
```

Without `server_default`, PostgreSQL throws: `column "role" of relation "users" contains null values`. This is the most common migration error when adding non-nullable columns to existing tables.

---

### The three commands you use every day

```bash
# Generate a migration file from model changes
alembic revision --autogenerate -m "describe what changed"

# Apply all pending migrations
alembic upgrade head

# Roll back the last migration
alembic downgrade -1
```

**Always read the generated file before running `upgrade head`.** Autogenerate is good but not perfect — it misses some things (like changes to custom enum values) and occasionally generates incorrect SQL for complex types. Treat it as a first draft, not a final answer.

---

### `env.py` — how Alembic finds your models

```python
# Pull DATABASE_URL from .env instead of hardcoding in alembic.ini
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

# The metadata Alembic diffs against
target_metadata = Base.metadata

# compare_type=True — detects column type changes, not just additions/removals
context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
```

`compare_type=True` is important. Without it, if you change `String` to `String(200)`, Alembic won't detect the change. With it, type changes produce `op.alter_column()` calls in the generated migration.

---

## 15. Verification Checklist

After applying the migration and restarting, verify each of these:

### Check 1 — Migration status

```bash
alembic current
```

Should output: `1849d5a8a716 (head)` (or your latest revision ID). If it shows nothing or `None`, the migration didn't run.

---

### Check 2 — Tables exist in the database

Run in your Supabase SQL editor or `psql`:

```sql
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
ORDER BY table_name;
```

Expected output:
```
alembic_version
coding_sessions
journal_entries
projects
refresh_tokens
tasks
users
```

---

### Check 3 — User columns were added

```sql
SELECT column_name, data_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_name = 'users'
ORDER BY ordinal_position;
```

You should see `role`, `is_verified`, and `totp_secret` in the results with correct types.

---

### Check 4 — Server starts without errors

```bash
uvicorn app.main:app --reload
```

A clean start — no `InvalidRequestError`, no import errors — means all models loaded and SQLAlchemy resolved all relationships successfully.

---

### Check 5 — Login still works

POST to `/api/auth/login` with your existing user credentials. A successful login confirms that:
- The `User` model loads correctly with the new relationships
- `deps.py` can still decode tokens and query the users table
- The auth flow is unaffected by the new models

---

## 16. Design Decisions Summary

| Decision | Reasoning |
|---|---|
| `ARRAY(String)` for `tech_stack` and `tags` | Native PostgreSQL arrays enable `WHERE 'React' = ANY(tech_stack)` — no string parsing needed |
| `session_date` as `Date` not `DateTime` | Analytics queries group by calendar day, not exact timestamp. Developers log sessions retrospectively |
| `duration_mins` as `Integer` | Integer arithmetic is exact. Floating point time accumulation drifts and is unreliable |
| `time_logged` on `Task` in minutes | `SUM(time_logged)` across tasks gives exact totals instantly |
| `completed_at` timestamp on `Task` | Enables "time to completion" analytics — impossible with just a status enum |
| `ondelete="SET NULL"` on `session.project_id` | Session history survives project deletion — losing history is worse than a null FK |
| `cascade="all, delete-orphan"` from `User` | Deleting a user cleans up everything they own — no orphaned rows, no FK constraint errors |
| `back_populates` over `backref` | Both sides of every relationship are visible and explicit in their own file |
| `JournalPublicResponse` as a separate schema | Never exposes `user_id` in public endpoints — minimal exposure is the default |
| Tag lowercasing in validator | Normalizes at write time so `"React"` and `"react"` are the same tag without any query-time gymnastics |
| `models/__init__.py` as central import | Guarantees all models load together before SQLAlchemy resolves relationship string references |
| `# noqa: F401` on model imports | Documents that side-effect imports are intentional, silences incorrect linter warnings |
| `server_default` in migration | Required when adding NOT NULL columns to tables that already have rows |

---

*Next: Phase 3 — Projects & Tasks API (services + routers)*
