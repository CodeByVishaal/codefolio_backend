# DevPulse — Phase 6 Documentation
## Analytics Engine

> **Stack:** FastAPI · SQLAlchemy ORM · PostgreSQL · Pydantic v2  
> **Phase goal:** Build the analytics layer — five endpoints that transform raw session and task data into dashboard-ready numbers, trends, breakdowns, and streak calculations.

---

## Table of Contents

1. [Overview](#1-overview)
2. [What Makes Analytics Different](#2-what-makes-analytics-different)
3. [No New Migration Needed](#3-no-new-migration-needed)
4. [schemas/analytics.py](#4-schemasanalyticspy)
5. [services/analytics_service.py](#5-servicesanalytics_servicepy)
6. [routers/analytics.py](#6-routersanalyticspy)
7. [main.py — Updated](#7-mainpy--updated)
8. [SQL Patterns Deep Dive](#8-sql-patterns-deep-dive)
9. [Request Lifecycle Walkthroughs](#9-request-lifecycle-walkthroughs)
10. [Verification & Manual Testing](#10-verification--manual-testing)
11. [Design Decisions Summary](#11-design-decisions-summary)

---

## 1. Overview

Phases 3–5 were about creating and reading individual records — CRUD operations. Phase 6 is entirely different: it takes thousands of individual records and **transforms them into insights**. A developer who has logged 200 sessions doesn't want to see 200 rows — they want to see "I coded 47 hours this month, my longest streak was 12 days, and I spend 60% of my time on DevPulse."

That transformation from raw records to insights is what analytics does.

### Files created in this phase

```
app/
├── schemas/
│   └── analytics.py          ← new: response shapes for all analytics endpoints
├── services/
│   └── analytics_service.py  ← new: all aggregation logic
├── routers/
│   └── analytics.py          ← new: five endpoints
└── main.py                   ← updated: registers analytics router
```

### Complete endpoint list

| Method | URL | Parameters | What it returns |
|--------|-----|-----------|-----------------|
| `GET` | `/api/analytics/summary` | none | Lifetime totals + streak |
| `GET` | `/api/analytics/daily` | `date_from`, `date_to` (required) | Day-by-day activity |
| `GET` | `/api/analytics/weekly` | `date_from`, `date_to` (required) | Week-by-week activity |
| `GET` | `/api/analytics/projects` | `date_from`, `date_to` (optional) | Per-project time breakdown |
| `GET` | `/api/analytics/streak` | none | Current + longest streak |

All five endpoints require authentication. All five are read-only — no data is created or modified.

---

## 2. What Makes Analytics Different

Every previous phase followed the same pattern:

```
Client sends data → Service validates + stores → Service reads + returns
```

Analytics breaks this pattern. There is no "storing" step. The service only reads, but it reads in a fundamentally different way: instead of fetching rows and returning them, it asks the database to **aggregate rows and return summaries**.

### Row fetching vs aggregation

```python
# Fetching rows — Phase 3/4/5 pattern
sessions = db.query(CodingSession).filter(
    CodingSession.user_id == user.id
).all()
# Returns: [Session(id=1, mins=90), Session(id=2, mins=120), ...]
# Python receives ALL rows

# Aggregation — Phase 6 pattern
total = db.query(
    func.sum(CodingSession.duration_mins)
).filter(CodingSession.user_id == user.id).scalar()
# Returns: 210
# Python receives ONE number — the database did the work
```

The difference becomes significant at scale. A user with 500 sessions:

| Approach | Rows transferred | Python work |
|----------|-----------------|-------------|
| Fetch + sum in Python | 500 rows | Loop through all, sum `duration_mins` |
| SQL `SUM()` | 1 row | Nothing — just read the result |

SQL aggregation is always faster, uses less memory, and puts the computational load where it belongs — inside the database, close to the data.

### New SQL concepts introduced in this phase

| Concept | Where used | What it does |
|---------|-----------|--------------|
| `GROUP BY` | daily, weekly, project breakdown | Splits rows into groups, applies aggregate per group |
| `func.date_trunc()` | weekly breakdown | Truncates a date to the start of its week |
| `text()` | weekly, project breakdown | Passes raw SQL strings for aliases in `ORDER BY` |
| `.distinct()` | streak | De-duplicates rows — one entry per unique date |
| Python streak algorithm | `_calculate_streak` | Consecutive-day detection — cleaner in Python than SQL |

---

## 3. No New Migration Needed

Phase 6 is purely a read layer. It queries `coding_sessions`, `projects`, and `tasks` — all created in the Phase 2 migration. No new tables, no new columns, no `alembic revision` needed.

Confirm your database is at the correct revision before starting:

```bash
alembic current
# Should show your Phase 2 revision as (head)
```

---

## 4. `schemas/analytics.py`

```python
from pydantic import BaseModel
from datetime import date
from typing import Optional
```

All six schemas in this file are plain `BaseModel` with **no `model_config`**. None of them are mapped from SQLAlchemy model instances — they are constructed directly in the service from query results. `from_attributes=True` is only needed when reading from ORM objects, so it is deliberately absent here.

---

### `DailyActivity`

```python
class DailyActivity(BaseModel):
    date:           date
    total_mins:     int
    total_hours:    float
    total_sessions: int
```

One instance of this schema represents one calendar day that has at least one coding session. The frontend receives a list of these and uses them to draw bar charts or line charts.

**`date` type** — Pydantic serialises Python's `datetime.date` to an ISO 8601 string (`"2026-03-23"`) in the JSON response automatically. The frontend receives a clean date string without any time component.

**Both `total_mins` and `total_hours` are included** — `total_mins` is the raw integer (exact, no rounding). `total_hours` is the human-readable float (`1.5` not `90`). The frontend can use whichever fits the chart. Having both avoids the frontend needing to do the conversion with potential float precision issues.

**Days with no sessions are absent** — if the user coded on March 1st, 3rd, and 5th, the response has three items — not 31 items with zeros for the days without sessions. The frontend is responsible for filling gaps with zero when rendering a continuous chart. This keeps the response small and puts display logic in the UI where it belongs.

---

### `WeeklyActivity`

```python
class WeeklyActivity(BaseModel):
    week_start:     date
    total_mins:     int
    total_hours:    float
    total_sessions: int
```

One instance represents one calendar week. `week_start` is always a Monday — the ISO standard week start. A week from March 23rd to March 29th would have `week_start: "2026-03-23"` (if that's a Monday).

The frontend can use `week_start` as the x-axis label on a trend chart: "Week of Mar 23", "Week of Mar 30", etc.

---

### `ProjectBreakdown`

```python
class ProjectBreakdown(BaseModel):
    project_id:     int
    project_title:  str
    total_mins:     int
    total_hours:    float
    total_sessions: int
```

One instance represents one project's contribution to the user's total coding time. The list is ordered by `total_mins` descending — the project with the most time spent comes first.

**`project_title` is included** — the frontend needs the project name to label chart segments. Including it here means the frontend does not need to make a second API call to `/projects` just to get names. Data that will always be displayed together should be fetched together.

---

### `StreakData`

```python
class StreakData(BaseModel):
    current_streak:  int
    longest_streak:  int
    last_coded_date: Optional[date]
```

**`current_streak`** — the number of consecutive days the user has coded, counting back from today or yesterday. A streak is still alive if the user coded yesterday but not yet today. It breaks if the most recent session was two or more days ago.

**`longest_streak`** — the all-time longest consecutive run ever recorded. This doesn't change unless the user beats their record. It serves as a personal best to aim for.

**`last_coded_date: Optional[date]`** — `None` if the user has never logged a session. Otherwise, the most recent `session_date`. The frontend can use this to show "Last coded: 2 days ago" or to determine whether to display a streak flame icon.

---

### `AnalyticsSummary`

```python
class AnalyticsSummary(BaseModel):
    total_mins:            int
    total_hours:           float
    total_sessions:        int
    total_projects:        int
    total_tasks_completed: int
    streak:                StreakData
```

The top-level dashboard response. These are the "hero numbers" shown at the top of the analytics page — the first thing the user sees when they open their dashboard.

**`streak: StreakData`** — the streak data is nested as a sub-object inside the summary. This groups related data cleanly: overall totals at the top level, streak details nested. The frontend can destructure it naturally.

---

## 5. `services/analytics_service.py`

```python
from datetime import date, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func, text

from app.models.session import CodingSession
from app.models.project import Project
from app.models.task import Task, TaskStatus
from app.models.users import User
from app.schemas.analytics import (
    AnalyticsSummary, DailyActivity, WeeklyActivity,
    ProjectBreakdown, StreakData,
)
```

**`from sqlalchemy import func, text`** — two new imports not seen before Phase 6.

- `func` — SQLAlchemy's gateway to SQL aggregate functions. Any SQL function can be called through it: `func.sum(...)`, `func.count(...)`, `func.date_trunc(...)`. SQLAlchemy passes these to the database dialect and builds the correct SQL syntax.
- `text()` — wraps a raw SQL string and tells SQLAlchemy to pass it literally to the database. Used in `ORDER BY` clauses when referencing computed column aliases that SQLAlchemy's ORM can't resolve by name.

---

### `_to_hours` — shared helper

```python
def _to_hours(mins: int | None) -> float:
    """Convert minutes to hours, rounded to one decimal place."""
    return round((mins or 0) / 60, 1)
```

**`mins or 0`** — `SQL SUM()` on an empty set returns `NULL`, which becomes `None` in Python. `None or 0` evaluates to `0`, making division safe. Without this guard, `None / 60` would raise `TypeError: unsupported operand type(s) for /: 'NoneType' and 'int'`.

**`round(..., 1)`** — one decimal place for display. `210 / 60 = 3.5`. Without rounding, floating point arithmetic can produce `3.4999999999999996` or `3.5000000000000004`. `round(3.5, 1)` always gives `3.5`.

**Why a dedicated helper?** The same conversion — minutes to hours, rounded — happens five times across the service: once in summary, once in daily, once in weekly, once per row in project breakdown, and once in streak. A shared helper means the rounding logic is defined once. If you later decide to round to 2 decimal places, you change one line.

---

### `_calculate_streak`

```python
def _calculate_streak(dates: list[date]) -> tuple[int, int]:
    if not dates:
        return 0, 0

    today = date.today()
```

This is the only function in Phase 6 that uses Python logic rather than SQL. Consecutive-day detection requires comparing adjacent elements in a sorted list — an operation that SQL can do with window functions but Python expresses more clearly. The function receives a pre-sorted (descending) list of unique coding dates.

---

#### Early exit for empty history

```python
if not dates:
    return 0, 0
```

If the user has never logged a session, there are no dates. Both streaks are 0. Return immediately — everything below would fail or give meaningless results on an empty list.

---

#### Current streak logic

```python
most_recent = dates[0]
if most_recent < today - timedelta(days=1):
    current_streak = 0
else:
    current_streak = 1
    for i in range(1, len(dates)):
        if dates[i] == dates[i - 1] - timedelta(days=1):
            current_streak += 1
        else:
            break
```

**`dates[0]`** — the most recent date, since the list is sorted descending.

**`today - timedelta(days=1)`** — yesterday's date. The streak is still alive if the user coded today or yesterday. If `most_recent < yesterday`, the streak is broken — the user missed at least two days.

**Why allow yesterday?** Developers often finish a session late at night and log it. If you only allow "today", a user who coded at 11:30pm and logs it the next morning would see their streak break. Allowing yesterday handles this gracefully.

**The counting loop:**

```python
for i in range(1, len(dates)):
    if dates[i] == dates[i - 1] - timedelta(days=1):
        current_streak += 1
    else:
        break
```

Starting from index 1, compare each date to the one before it. Since the list is descending:
- `dates[0]` = today
- `dates[1]` should be yesterday (`dates[0] - 1 day`)
- `dates[2]` should be two days ago (`dates[1] - 1 day`)
- ...

If any pair has a gap larger than 1 day, `break` — the streak ends there. The `break` is crucial: without it, the loop would count non-consecutive dates as part of the streak.

**Example with dates `[2026-03-25, 2026-03-24, 2026-03-22]` and today = 2026-03-25:**
- `most_recent = 2026-03-25` — today, streak is alive
- `i=1`: `dates[1](03-24) == dates[0](03-25) - 1 day` → True, `current_streak = 2`
- `i=2`: `dates[2](03-22) == dates[1](03-24) - 1 day` → False (03-23 ≠ 03-22), `break`
- Result: `current_streak = 2`

---

#### Longest streak logic

```python
longest = 1
run = 1
ascending = list(reversed(dates))
for i in range(1, len(ascending)):
    if ascending[i] == ascending[i - 1] + timedelta(days=1):
        run += 1
        longest = max(longest, run)
    else:
        run = 1

return current_streak, longest
```

**`list(reversed(dates))`** — reverse to ascending order (oldest first). Walking oldest → newest makes the addition logic natural: each date should be exactly one day after the previous.

**`run` and `longest`** — two separate counters. `run` tracks the current consecutive sequence. `longest` remembers the best `run` seen so far. Every time `run` increments, `max(longest, run)` updates `longest` if the current run has beaten the record.

**`run = 1` on break** — when a gap is found, reset `run` to 1 (not 0), because the current date itself is a valid single-day run.

**Example with ascending `[2026-03-20, 2026-03-21, 2026-03-22, 2026-03-25, 2026-03-26]`:**
- `i=1`: `03-21 == 03-20 + 1 day` → True, `run=2`, `longest=2`
- `i=2`: `03-22 == 03-21 + 1 day` → True, `run=3`, `longest=3`
- `i=3`: `03-25 == 03-22 + 1 day` → False (gap), `run=1`
- `i=4`: `03-26 == 03-25 + 1 day` → True, `run=2`, `longest` stays 3
- Result: `longest = 3`

---

### `get_summary`

```python
def get_summary(user: User, db: Session) -> AnalyticsSummary:
```

Runs five SQL queries. All use `.scalar()` — the correct method for single-value aggregate results.

---

#### Four aggregate queries

```python
total_mins = db.query(
    func.sum(CodingSession.duration_mins)
).filter(CodingSession.user_id == user.id).scalar() or 0
```

`func.sum(CodingSession.duration_mins)` generates `SELECT SUM(duration_mins) FROM coding_sessions WHERE user_id = ?`. One number returned. `.scalar()` unwraps it directly.

```python
total_sessions = db.query(
    func.count(CodingSession.id)
).filter(CodingSession.user_id == user.id).scalar() or 0
```

`COUNT(id)` counts non-null rows. Using `id` (the primary key) is conventional — it's never null and always indexed. `COUNT(*)` would also work but `COUNT(id)` is more explicit about what you're counting.

```python
total_projects = db.query(
    func.count(Project.id)
).filter(Project.user_id == user.id).scalar() or 0
```

Straightforward count across the projects table filtered by owner.

```python
total_tasks_completed = db.query(
    func.count(Task.id)
).join(Project, Task.project_id == Project.id).filter(
    Project.user_id == user.id,
    Task.status == TaskStatus.done,
).scalar() or 0
```

Tasks have no `user_id`. To count a user's completed tasks, join tasks to projects and filter by `projects.user_id`. This was established in Phase 5. The generated SQL:

```sql
SELECT COUNT(tasks.id)
FROM tasks
JOIN projects ON tasks.project_id = projects.id
WHERE projects.user_id = ?
  AND tasks.status = 'done'
```

---

#### Fetching dates for streak

```python
date_rows = db.query(CodingSession.session_date).filter(
    CodingSession.user_id == user.id
).distinct().order_by(CodingSession.session_date.desc()).all()

dates = [row.session_date for row in date_rows]
```

**`db.query(CodingSession.session_date)`** — queries only the `session_date` column, not the entire row. This is a column-level projection. For a user with 500 sessions, this transfers 500 date values instead of 500 full rows with all columns. Much less data across the network.

**`.distinct()`** — de-duplicates the dates. A user can log multiple sessions on the same day (morning and evening, for example). For streak calculation, what matters is whether they coded at all on a given day — not how many sessions they had. `.distinct()` ensures each calendar date appears only once.

Generated SQL:
```sql
SELECT DISTINCT session_date
FROM coding_sessions
WHERE user_id = ?
ORDER BY session_date DESC
```

**`[row.session_date for row in date_rows]`** — `date_rows` is a list of single-column tuples, like `[(date(2026,3,25),), (date(2026,3,24),)]`. This list comprehension unwraps them into plain `date` objects: `[date(2026,3,25), date(2026,3,24)]`. The `_calculate_streak` function receives this clean list.

---

### `get_daily`

```python
def get_daily(
    user: User,
    db: Session,
    date_from: date,
    date_to: date,
) -> list[DailyActivity]:
```

**Both date parameters are required** — unlike session filtering where dates are optional, analytics charts always need a range. "Show me all daily data ever" is not a useful chart and could be enormous.

---

#### The GROUP BY query

```python
rows = db.query(
    CodingSession.session_date,
    func.sum(CodingSession.duration_mins).label("total_mins"),
    func.count(CodingSession.id).label("total_sessions"),
).filter(
    CodingSession.user_id == user.id,
    CodingSession.session_date >= date_from,
    CodingSession.session_date <= date_to,
).group_by(
    CodingSession.session_date
).order_by(
    CodingSession.session_date.asc()
).all()
```

This query introduces `GROUP BY`. Without it, `SUM` and `COUNT` would aggregate across all matching rows and return one single row. With `GROUP BY session_date`, the matching rows are first split into groups — one group per unique date — then `SUM` and `COUNT` are applied to each group separately.

Generated SQL:
```sql
SELECT session_date,
       SUM(duration_mins) AS total_mins,
       COUNT(id) AS total_sessions
FROM coding_sessions
WHERE user_id = ?
  AND session_date >= ?
  AND session_date <= ?
GROUP BY session_date
ORDER BY session_date ASC
```

For a user who logged 3 sessions on March 23rd (30, 60, and 45 minutes), this returns one row: `(2026-03-23, 135, 3)`. Not three rows.

**`.label("total_mins")`** — gives the aggregate column a name accessible as `row.total_mins` in Python. Without `.label()`, the column has an auto-generated name that varies by database. Always label your aggregate columns.

**`order_by(CodingSession.session_date.asc())`** — oldest to newest. Charts read left to right — time must flow forward.

---

#### Building the response

```python
return [
    DailyActivity(
        date=row.session_date,
        total_mins=row.total_mins,
        total_hours=_to_hours(row.total_mins),
        total_sessions=row.total_sessions,
    )
    for row in rows
]
```

A list comprehension that transforms each database row into a `DailyActivity` schema instance. `_to_hours(row.total_mins)` converts minutes to hours using the shared helper. This is clean, readable, and runs in O(n) where n is the number of days with sessions.

---

### `get_weekly`

```python
def get_weekly(
    user: User,
    db: Session,
    date_from: date,
    date_to: date,
) -> list[WeeklyActivity]:
```

The weekly breakdown uses a PostgreSQL-specific function: `DATE_TRUNC`. This is the most database-specific code in the entire project.

---

#### `func.date_trunc`

```python
rows = db.query(
    func.date_trunc("week", CodingSession.session_date).label("week_start"),
    func.sum(CodingSession.duration_mins).label("total_mins"),
    func.count(CodingSession.id).label("total_sessions"),
).filter(
    CodingSession.user_id == user.id,
    CodingSession.session_date >= date_from,
    CodingSession.session_date <= date_to,
).group_by(
    text("week_start")
).order_by(
    text("week_start ASC")
).all()
```

**`func.date_trunc("week", CodingSession.session_date)`** — truncates a date to the beginning of its ISO week (Monday). Examples:
- `2026-03-25` (Wednesday) → `2026-03-23` (Monday)
- `2026-03-23` (Monday) → `2026-03-23` (Monday)
- `2026-03-29` (Sunday) → `2026-03-23` (Monday)

All three dates belong to the same week and produce the same truncated date. When `GROUP BY week_start` runs, all three are in the same group. Their durations are summed together.

Generated SQL:
```sql
SELECT DATE_TRUNC('week', session_date) AS week_start,
       SUM(duration_mins) AS total_mins,
       COUNT(id) AS total_sessions
FROM coding_sessions
WHERE user_id = ?
  AND session_date >= ?
  AND session_date <= ?
GROUP BY week_start
ORDER BY week_start ASC
```

---

#### `text("week_start")` in `group_by` and `order_by`

```python
.group_by(text("week_start"))
.order_by(text("week_start ASC"))
```

SQLAlchemy's ORM layer cannot reference a computed alias (`week_start`) in `group_by` or `order_by` by Python name — it doesn't know that string maps to the `DATE_TRUNC(...)` expression. `text()` passes the string `"week_start"` literally to PostgreSQL. PostgreSQL's SQL parser can resolve it because the alias is defined in the `SELECT` clause.

Without `text()`, you would write:

```python
.group_by(func.date_trunc("week", CodingSession.session_date))
.order_by(func.date_trunc("week", CodingSession.session_date).asc())
```

This works but repeats the expression twice. The `text()` alias approach is cleaner and avoids repeating the `date_trunc` expression.

---

#### `.date()` on the result

```python
return [
    WeeklyActivity(
        week_start=row.week_start.date(),
        ...
    )
    for row in rows
]
```

**`row.week_start.date()`** — `DATE_TRUNC` in PostgreSQL returns a `TIMESTAMP` (datetime with time component), not a plain `DATE`. The result in Python is a `datetime` object like `datetime(2026, 3, 23, 0, 0, 0)`. Calling `.date()` strips the time component, giving a clean `date(2026, 3, 23)`. This matches the `week_start: date` declared in the schema.

---

### `get_project_breakdown`

```python
def get_project_breakdown(
    user: User,
    db: Session,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[ProjectBreakdown]:
```

Date filters are optional here — `None` means all-time breakdown.

---

#### The JOIN query

```python
query = db.query(
    Project.id.label("project_id"),
    Project.title.label("project_title"),
    func.sum(CodingSession.duration_mins).label("total_mins"),
    func.count(CodingSession.id).label("total_sessions"),
).join(
    Project, CodingSession.project_id == Project.id
).filter(
    CodingSession.user_id == user.id,
)
```

**`db.query(Project.id, Project.title, func.sum(...), func.count(...))`** — the query selects columns from two different tables: `projects.id`, `projects.title`, and aggregates from `coding_sessions`. This is possible because of the JOIN that combines them.

**`.join(Project, CodingSession.project_id == Project.id)`** — an `INNER JOIN`. Only rows where `coding_sessions.project_id` matches a `projects.id` are included. Sessions with `project_id = NULL` are excluded automatically — an INNER JOIN requires a match on both sides.

Generated SQL:
```sql
SELECT projects.id AS project_id,
       projects.title AS project_title,
       SUM(coding_sessions.duration_mins) AS total_mins,
       COUNT(coding_sessions.id) AS total_sessions
FROM coding_sessions
JOIN projects ON coding_sessions.project_id = projects.id
WHERE coding_sessions.user_id = ?
GROUP BY projects.id, projects.title
ORDER BY total_mins DESC
```

**`GROUP BY projects.id, projects.title`** — when using `GROUP BY` with a JOIN, all non-aggregate columns in the `SELECT` must appear in the `GROUP BY`. Both `projects.id` and `projects.title` are non-aggregate, so both must be listed.

---

#### Optional date filters applied after the base query

```python
if date_from:
    query = query.filter(CodingSession.session_date >= date_from)
if date_to:
    query = query.filter(CodingSession.session_date <= date_to)

rows = query.group_by(
    Project.id, Project.title
).order_by(
    text("total_mins DESC")
).all()
```

**Composable query building** — the base query is built first. Filters are added conditionally. `.group_by()` and `.order_by()` are appended last. The query only executes when `.all()` is called. This is a pattern used throughout the codebase — it keeps the core logic readable and the filtering logic separate.

**`text("total_mins DESC")`** — same reason as `text("week_start ASC")` in the weekly query. The `total_mins` alias (defined by `.label("total_mins")`) cannot be referenced by name through SQLAlchemy's ORM layer in `order_by`. `text()` passes it directly to PostgreSQL.

---

### `get_streak`

```python
def get_streak(user: User, db: Session) -> StreakData:
    date_rows = db.query(CodingSession.session_date).filter(
        CodingSession.user_id == user.id
    ).distinct().order_by(CodingSession.session_date.desc()).all()

    dates = [row.session_date for row in date_rows]
    current_streak, longest_streak = _calculate_streak(dates)

    return StreakData(
        current_streak=current_streak,
        longest_streak=longest_streak,
        last_coded_date=dates[0] if dates else None,
    )
```

This function is lean by design — it delegates entirely to `_calculate_streak`. The database work (fetching distinct dates) and the Python work (streak calculation) are separated into clear steps.

**`dates[0] if dates else None`** — `dates[0]` is the most recent session date (list is sorted descending). The ternary guard handles the case where a user has no sessions at all — `dates` would be an empty list and `dates[0]` would raise `IndexError`.

---

## 6. `routers/analytics.py`

```python
from datetime import date
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import Optional

router = APIRouter(prefix="/analytics", tags=["analytics"])
```

**`prefix="/analytics"`** — all five routes start with `/analytics`. Combined with `prefix="/api"` in `main.py`, the full paths are `/api/analytics/summary`, `/api/analytics/daily`, etc.

---

### `get_summary` route

```python
@router.get("/summary", response_model=AnalyticsSummary)
def get_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return analytics_service.get_summary(current_user, db)
```

No query parameters — summary is always lifetime totals. The authentication dependency ensures this returns only the current user's data.

---

### `get_daily` route

```python
@router.get("/daily", response_model=list[DailyActivity])
def get_daily(
    date_from: date = Query(description="Start date (YYYY-MM-DD)"),
    date_to:   date = Query(description="End date (YYYY-MM-DD)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return analytics_service.get_daily(current_user, db, date_from, date_to)
```

**`date = Query(...)`** — required parameter (no `default=None`). If the client omits either date, FastAPI returns `422 Unprocessable Entity` automatically. A chart without a date range has no meaningful boundaries — requiring both is the correct design.

**Pydantic auto-parses `date` from strings** — `?date_from=2026-03-01` is automatically converted to `date(2026, 3, 1)`. If the format is invalid, FastAPI returns `422` before the handler runs. Zero parsing code needed.

---

### `get_weekly` route

```python
@router.get("/weekly", response_model=list[WeeklyActivity])
def get_weekly(
    date_from: date = Query(description="Start date (YYYY-MM-DD)"),
    date_to:   date = Query(description="End date (YYYY-MM-DD)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return analytics_service.get_weekly(current_user, db, date_from, date_to)
```

Same structure as `get_daily`. Both dates required. The service handles the `DATE_TRUNC` week calculation — the router is just the HTTP boundary.

---

### `get_project_breakdown` route

```python
@router.get("/projects", response_model=list[ProjectBreakdown])
def get_project_breakdown(
    date_from: Optional[date] = Query(default=None, description="Start date (YYYY-MM-DD)"),
    date_to:   Optional[date] = Query(default=None, description="End date (YYYY-MM-DD)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return analytics_service.get_project_breakdown(current_user, db, date_from, date_to)
```

**`Optional[date] = Query(default=None)`** — dates are optional here. Both `GET /api/analytics/projects` (all-time) and `GET /api/analytics/projects?date_from=2026-03-01&date_to=2026-03-31` (monthly) are valid and meaningful.

---

### `get_streak` route

```python
@router.get("/streak", response_model=StreakData)
def get_streak(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return analytics_service.get_streak(current_user, db)
```

No parameters — a streak is always calculated from all sessions ever. You can't ask "what was my streak in March?" in any meaningful way, so no date filter is offered.

---

## 7. `main.py` — Updated

```python
from app.routers import auth, projects, tasks, sessions, journal, users, analytics

app.include_router(analytics.router, prefix="/api")
```

One new import, one new `include_router`. The analytics router registers all five endpoints under `/api/analytics/...`.

### Complete backend URL map

```
Phase 1 — Auth
  POST  /api/auth/register
  POST  /api/auth/login
  POST  /api/auth/refresh
  POST  /api/auth/logout

Phase 3 — Projects & Tasks
  POST   /api/projects
  GET    /api/projects
  GET    /api/projects/{id}
  PATCH  /api/projects/{id}
  DELETE /api/projects/{id}
  POST   /api/projects/{id}/tasks
  GET    /api/projects/{id}/tasks
  PATCH  /api/projects/{id}/tasks/{task_id}
  DELETE /api/projects/{id}/tasks/{task_id}
  POST   /api/projects/{id}/tasks/{task_id}/log-time

Phase 4 — Sessions & Journal
  POST   /api/sessions
  GET    /api/sessions/summary
  GET    /api/sessions
  GET    /api/sessions/{id}
  PATCH  /api/sessions/{id}
  DELETE /api/sessions/{id}
  POST   /api/journal
  GET    /api/journal
  GET    /api/journal/{id}
  PATCH  /api/journal/{id}
  DELETE /api/journal/{id}

Phase 5 — User Profiles
  GET    /api/users/me
  GET    /api/users/{id}/profile

Phase 6 — Analytics
  GET    /api/analytics/summary
  GET    /api/analytics/daily
  GET    /api/analytics/weekly
  GET    /api/analytics/projects
  GET    /api/analytics/streak
```

---

## 8. SQL Patterns Deep Dive

Phase 6 introduces three SQL patterns not seen in any earlier phase. Understanding them is essential for writing analytics queries correctly.

---

### Pattern 1 — `GROUP BY` with aggregate functions

```sql
SELECT session_date,
       SUM(duration_mins) AS total_mins,
       COUNT(id) AS total_sessions
FROM coding_sessions
WHERE user_id = ?
GROUP BY session_date
```

**How `GROUP BY` works:**

1. The `WHERE` clause filters the rows to those matching `user_id = ?`
2. The remaining rows are split into groups — one group per unique `session_date` value
3. `SUM` and `COUNT` are applied to each group independently
4. One result row is returned per group

Without `GROUP BY`, `SUM` and `COUNT` would aggregate all matching rows into one single result row. With `GROUP BY`, you get one result row per unique value of the grouped column.

**The rule:** every column in the `SELECT` that is not an aggregate function must appear in the `GROUP BY`. Violating this rule causes a database error in PostgreSQL (some other databases are more lenient but produce undefined results).

---

### Pattern 2 — `DATE_TRUNC` for week/month/year grouping

```sql
SELECT DATE_TRUNC('week', session_date) AS week_start, ...
FROM coding_sessions
GROUP BY week_start
```

`DATE_TRUNC(precision, date)` truncates a date to the specified unit:

| Input date | Precision | Output |
|-----------|-----------|--------|
| `2026-03-25` | `'week'` | `2026-03-23 00:00:00` (Monday) |
| `2026-03-25` | `'month'` | `2026-03-01 00:00:00` |
| `2026-03-25` | `'year'` | `2026-01-01 00:00:00` |

By truncating all dates to the same precision, dates that belong to the same week (or month, or year) produce identical truncated values. `GROUP BY` then groups them together automatically.

**This is a PostgreSQL-specific function.** SQLite, MySQL, and other databases have different functions for the same purpose. Phase 6 assumes a PostgreSQL database (Supabase).

---

### Pattern 3 — `.distinct()` for unique values

```python
db.query(CodingSession.session_date).filter(
    CodingSession.user_id == user.id
).distinct().all()
```

`.distinct()` adds `SELECT DISTINCT` to the query. The database returns only unique values — duplicates are removed before the result is sent.

Without `.distinct()`, a user who logged 3 sessions on the same day would have that date appear 3 times in the results. For streak calculation, you only need to know whether they coded on a given day — not how many times. `.distinct()` removes the duplicates at the database level, keeping the data transferred to Python minimal.

---

## 9. Request Lifecycle Walkthroughs

### Getting the analytics summary

```
GET /api/analytics/summary
Cookie: access_token=eyJ...

1. FastAPI routes to get_summary() in routers/analytics.py

2. Depends(get_current_user) → User(id=3, name="Alex")
   (One DB query: SELECT * FROM users WHERE id = 3)

3. analytics_service.get_summary(user, db) runs:

   Query 1: SELECT SUM(duration_mins) FROM coding_sessions WHERE user_id = 3
   → .scalar() → 3840  (64 hours)

   Query 2: SELECT COUNT(id) FROM coding_sessions WHERE user_id = 3
   → .scalar() → 48

   Query 3: SELECT COUNT(id) FROM projects WHERE user_id = 3
   → .scalar() → 8

   Query 4: SELECT COUNT(tasks.id)
            FROM tasks
            JOIN projects ON tasks.project_id = projects.id
            WHERE projects.user_id = 3 AND tasks.status = 'done'
   → .scalar() → 47

   Query 5: SELECT DISTINCT session_date
            FROM coding_sessions
            WHERE user_id = 3
            ORDER BY session_date DESC
   → [date(2026,3,25), date(2026,3,24), date(2026,3,22), date(2026,3,20), ...]

4. _calculate_streak([date(2026,3,25), date(2026,3,24), ...]) called:
   → today = date(2026, 3, 25)
   → most_recent = date(2026, 3, 25) — today, streak alive
   → i=1: 03-24 == 03-25 - 1 day → True, current_streak=2
   → i=2: 03-22 == 03-24 - 1 day → False (gap on 03-23), break
   → current_streak = 2

   Longest streak calculation (ascending):
   [..., 03-20, 03-22, 03-24, 03-25]
   → 03-22 != 03-20 + 1 day: reset run=1
   → 03-24 != 03-22 + 1 day: reset run=1
   → 03-25 == 03-24 + 1 day: run=2, longest=2
   → longest_streak = 2

5. AnalyticsSummary constructed and returned
HTTP 200
{
  "total_mins": 3840,
  "total_hours": 64.0,
  "total_sessions": 48,
  "total_projects": 8,
  "total_tasks_completed": 47,
  "streak": {
    "current_streak": 2,
    "longest_streak": 2,
    "last_coded_date": "2026-03-25"
  }
}
```

Total database queries: **5** (1 auth + 4 aggregates + 1 distinct dates).

---

### Getting daily activity for a chart

```
GET /api/analytics/daily?date_from=2026-03-17&date_to=2026-03-23
Cookie: access_token=eyJ...

1. FastAPI routes to get_daily()
2. date_from="2026-03-17" → date(2026, 3, 17)
   date_to="2026-03-23" → date(2026, 3, 23)
   (Pydantic auto-parses — no handler code needed)

3. Depends(get_current_user) → User(id=3)

4. analytics_service.get_daily(user, db, date_from, date_to):

   SQL executed:
   SELECT session_date,
          SUM(duration_mins) AS total_mins,
          COUNT(id) AS total_sessions
   FROM coding_sessions
   WHERE user_id = 3
     AND session_date >= '2026-03-17'
     AND session_date <= '2026-03-23'
   GROUP BY session_date
   ORDER BY session_date ASC

   Result rows:
   (2026-03-18, 90, 1)
   (2026-03-20, 150, 2)
   (2026-03-22, 120, 1)
   (2026-03-23, 60, 1)

   (March 17th, 19th, 21st had no sessions — they're absent, not zero)

5. List comprehension builds DailyActivity objects:
   [
     DailyActivity(date=2026-03-18, total_mins=90, total_hours=1.5, total_sessions=1),
     DailyActivity(date=2026-03-20, total_mins=150, total_hours=2.5, total_sessions=2),
     DailyActivity(date=2026-03-22, total_mins=120, total_hours=2.0, total_sessions=1),
     DailyActivity(date=2026-03-23, total_mins=60, total_hours=1.0, total_sessions=1),
   ]

6. FastAPI validates each item through DailyActivity schema
HTTP 200
[
  {"date": "2026-03-18", "total_mins": 90, "total_hours": 1.5, "total_sessions": 1},
  {"date": "2026-03-20", "total_mins": 150, "total_hours": 2.5, "total_sessions": 2},
  {"date": "2026-03-22", "total_mins": 120, "total_hours": 2.0, "total_sessions": 1},
  {"date": "2026-03-23", "total_mins": 60, "total_hours": 1.0, "total_sessions": 1}
]

Frontend note: to draw a 7-day chart (March 17-23), the frontend fills
the missing days (17th, 19th, 21st) with zero-height bars.
```

---

### Getting the weekly trend

```
GET /api/analytics/weekly?date_from=2026-03-01&date_to=2026-03-31
Cookie: access_token=eyJ...

SQL executed:
SELECT DATE_TRUNC('week', session_date) AS week_start,
       SUM(duration_mins) AS total_mins,
       COUNT(id) AS total_sessions
FROM coding_sessions
WHERE user_id = 3
  AND session_date >= '2026-03-01'
  AND session_date <= '2026-03-31'
GROUP BY week_start
ORDER BY week_start ASC

All March sessions are bucketed by their Monday:
- 2026-03-05 session → week_start 2026-03-02 (Monday)
- 2026-03-18, 03-20, 03-22, 03-23 → week_start 2026-03-16 (Monday)

Result rows:
(2026-03-02 00:00:00, 240, 3)
(2026-03-09 00:00:00, 180, 2)
(2026-03-16 00:00:00, 420, 4)
(2026-03-23 00:00:00, 60, 1)

Note: results are TIMESTAMPS from DATE_TRUNC

.date() strips the time component:
week_start = datetime(2026, 3, 16, 0, 0).date() = date(2026, 3, 16)

HTTP 200
[
  {"week_start": "2026-03-02", "total_mins": 240, "total_hours": 4.0, "total_sessions": 3},
  {"week_start": "2026-03-09", "total_mins": 180, "total_hours": 3.0, "total_sessions": 2},
  {"week_start": "2026-03-16", "total_mins": 420, "total_hours": 7.0, "total_sessions": 4},
  {"week_start": "2026-03-23", "total_mins": 60,  "total_hours": 1.0, "total_sessions": 1}
]
```

---

## 10. Verification & Manual Testing

First, ensure you have sessions logged across multiple days (from Phase 4 testing) and at least some tasks marked `done` (from Phase 3 testing). Analytics needs existing data to aggregate.

---

### Summary

```
GET /api/analytics/summary
```

Expected: an object with `total_mins`, `total_hours`, `total_sessions`, `total_projects`, `total_tasks_completed`, and a nested `streak` object.

**Verify accuracy manually:**
- `total_sessions` should match the count in `GET /api/sessions`
- `total_hours` should equal `sum of all duration_mins / 60`, rounded to 1 decimal
- `total_projects` should match the count in `GET /api/projects`
- `total_tasks_completed` should match tasks with `status: "done"` across all your projects

---

### Daily

```
GET /api/analytics/daily?date_from=2026-03-01&date_to=2026-03-31
```

Expected: one entry per day you logged a session. Days without sessions are absent. Each entry has `date`, `total_mins`, `total_hours`, `total_sessions`. Sum all `total_mins` values — the total should match what `summary.total_mins` shows for the same period.

**Test missing required parameters:**
```
GET /api/analytics/daily
```
Expected: `422` — both `date_from` and `date_to` are required.

---

### Weekly

```
GET /api/analytics/weekly?date_from=2026-01-01&date_to=2026-03-31
```

Expected: one entry per calendar week that has sessions. Each `week_start` must be a Monday. Verify by checking: `date(week_start).weekday()` — Monday is `0` in Python.

If you have sessions on `2026-03-23` (Wednesday) and `2026-03-25` (Friday), both should appear in the same week entry with `week_start: "2026-03-23"` (that Monday).

---

### Project breakdown

```
GET /api/analytics/projects
```

Expected: projects ordered by `total_mins` descending. Sessions with no project are absent. Sum all `total_mins` values — they won't equal `summary.total_mins` because project-less sessions are excluded.

```
GET /api/analytics/projects?date_from=2026-03-01&date_to=2026-03-31
```

Expected: same but filtered to March sessions only. Some projects might drop off if you only logged sessions for them outside this range.

---

### Streak

**Test 1 — Active streak:**
Log a session with `session_date` = today. Call `GET /api/analytics/streak`. Expected: `current_streak >= 1`, `last_coded_date` = today.

**Test 2 — Continued streak:**
Log a session with `session_date` = yesterday. Call streak again. Expected: `current_streak >= 2`.

**Test 3 — Broken streak:**
Log a session with `session_date` = 5 days ago (no sessions between then and now). Call streak. Expected: `current_streak = 0` — the most recent session is more than 1 day ago so the streak is broken. `last_coded_date` should be today or yesterday (whichever was more recent).

**Test 4 — No sessions:**
If testing with a fresh account that has no sessions, `current_streak = 0`, `longest_streak = 0`, `last_coded_date = null`.

---

## 11. Design Decisions Summary

| Decision | Reasoning |
|---|---|
| All schemas are plain `BaseModel` with no `from_attributes` | Analytics schemas are constructed from query results, not mapped from SQLAlchemy ORM objects. `from_attributes` is only needed for ORM-mapped schemas |
| Both `total_mins` and `total_hours` in every response | Frontend can use whichever fits — raw integer for calculations, float for display. Avoids frontend needing to convert with potential precision issues |
| Days with no sessions are absent from daily response | Keeps the response small. The frontend is responsible for filling gaps with zero when rendering a continuous chart |
| `_to_hours` as a shared helper | Minutes-to-hours conversion happens five times across the service. One helper, one rounding rule, one place to change |
| Streak calculated in Python, not SQL | Consecutive-day detection is clearer in Python. SQL window functions work but are harder to read and debug. The input is small (only dates, not full rows) so Python processing is fast |
| `.distinct()` on session dates for streak | A user can log multiple sessions per day. Streak cares about whether they coded, not how many times. `.distinct()` ensures one date per day before the Python loop |
| `date_from` and `date_to` required on `daily` and `weekly` | An unbounded chart is meaningless and potentially enormous. Charts always have a time range |
| `date_from` and `date_to` optional on `projects` | All-time project breakdown ("what have I spent most time on?") is a meaningful view. Monthly breakdown is also useful. Both are valid |
| `func.date_trunc("week", ...)` for weekly grouping | PostgreSQL-native function. Truncates any date to its Monday, enabling clean `GROUP BY week`. More reliable than date arithmetic in Python |
| `text("week_start ASC")` in `order_by` | SQLAlchemy can't reference computed column aliases (`week_start`) by Python name in `ORDER BY`. `text()` passes the alias string directly to PostgreSQL which can resolve it |
| `row.week_start.date()` to strip timestamp | `DATE_TRUNC` returns a `TIMESTAMP` in PostgreSQL. `.date()` strips the time component to match the `date` type declared in `WeeklyActivity` |
| INNER JOIN in project breakdown | Excludes sessions with `project_id = NULL` automatically. Sessions without a project don't belong in a project-by-project breakdown |
| Projects ordered by `total_mins DESC` | Most time spent project first — the natural sort for a breakdown view. The biggest slice of the pie chart should be first in the data |
| `.scalar()` for single-value aggregates | Returns the unwrapped value directly (`5` not `(5,)`). Correct for any query that selects one column and has no `GROUP BY` |
| `or 0` on every `.scalar()` result | `SUM()` returns `NULL` on empty sets. `None or 0` prevents `TypeError` on division in `_to_hours`. Always include it on aggregate results |

---

*The backend is now complete. Next: Frontend Phase F-1 — Foundation, Auth, and Project Scaffold.*
