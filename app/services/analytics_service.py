from datetime import date, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func, text

from app.models.session import CodingSession
from app.models.project import Project
from app.models.task import Task, TaskStatus
from app.models.users import User
from app.schemas.analytics import (
    AnalyticsSummary,
    DailyActivity,
    WeeklyActivity,
    ProjectBreakdown,
    StreakData,
)


# ── Private helpers ───────────────────────────────────────────────────────────


def _to_hours(mins: int | None) -> float:
    """Convert minutes to hours, rounded to one decimal place."""
    return round((mins or 0) / 60, 1)


def _calculate_streak(dates: list[date]) -> tuple[int, int]:
    """
    Given a sorted (descending) list of unique coding dates,
    calculate the current streak and the all-time longest streak.

    Current streak: consecutive days counting back from today or yesterday.
    Longest streak: the longest consecutive run in the entire history.

    Returns: (current_streak, longest_streak)
    """
    if not dates:
        return 0, 0

    today = date.today()

    # ── Current streak ────────────────────────────────────────────────────────
    # The streak is still alive if the user coded today OR yesterday.
    # If the most recent session was two or more days ago, the streak is broken.
    most_recent = dates[0]
    if most_recent < today - timedelta(days=1):
        # Last session was 2+ days ago — streak is 0
        current_streak = 0
    else:
        # Count consecutive days backwards from the most recent date
        current_streak = 1
        for i in range(1, len(dates)):
            if dates[i] == dates[i - 1] - timedelta(days=1):
                current_streak += 1
            else:
                break

    # ── Longest streak ────────────────────────────────────────────────────────
    # Walk the entire history to find the longest consecutive run.
    # dates is sorted descending, so we reverse to walk oldest → newest.
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


# ── Summary ───────────────────────────────────────────────────────────────────


def get_summary(user: User, db: Session) -> AnalyticsSummary:
    """
    Lifetime totals for the authenticated user.
    Runs five SQL queries — all aggregations, no rows fetched into Python.
    """
    total_mins = (
        db.query(func.sum(CodingSession.duration_mins))
        .filter(CodingSession.user_id == user.id)
        .scalar()
        or 0
    )

    total_sessions = (
        db.query(func.count(CodingSession.id))
        .filter(CodingSession.user_id == user.id)
        .scalar()
        or 0
    )

    total_projects = (
        db.query(func.count(Project.id)).filter(Project.user_id == user.id).scalar()
        or 0
    )

    total_tasks_completed = (
        db.query(func.count(Task.id))
        .join(Project, Task.project_id == Project.id)
        .filter(
            Project.user_id == user.id,
            Task.status == TaskStatus.done,
        )
        .scalar()
        or 0
    )

    # Fetch distinct session dates for streak calculation
    # Only dates are fetched — not full rows — keeping the payload small
    date_rows = (
        db.query(CodingSession.session_date)
        .filter(CodingSession.user_id == user.id)
        .distinct()
        .order_by(CodingSession.session_date.desc())
        .all()
    )

    dates = [row.session_date for row in date_rows]
    current_streak, longest_streak = _calculate_streak(dates)

    return AnalyticsSummary(
        total_mins=total_mins,
        total_hours=_to_hours(total_mins),
        total_sessions=total_sessions,
        total_projects=total_projects,
        total_tasks_completed=total_tasks_completed,
        streak=StreakData(
            current_streak=current_streak,
            longest_streak=longest_streak,
            last_coded_date=dates[0] if dates else None,
        ),
    )


# ── Daily breakdown ────────────────────────────────────────────────────────────


def get_daily(
    user: User,
    db: Session,
    date_from: date,
    date_to: date,
) -> list[DailyActivity]:
    """
    Day-by-day coding activity for a date range.
    Returns one entry per day that has at least one session.
    Days with no sessions are omitted — the frontend fills gaps with zero.

    Used for: line charts, bar charts, calendar heatmaps.
    """
    rows = (
        db.query(
            CodingSession.session_date,
            func.sum(CodingSession.duration_mins).label("total_mins"),
            func.count(CodingSession.id).label("total_sessions"),
        )
        .filter(
            CodingSession.user_id == user.id,
            CodingSession.session_date >= date_from,
            CodingSession.session_date <= date_to,
        )
        .group_by(CodingSession.session_date)
        .order_by(CodingSession.session_date.asc())
        .all()
    )

    return [
        DailyActivity(
            date=row.session_date,
            total_mins=row.total_mins,
            total_hours=_to_hours(row.total_mins),
            total_sessions=row.total_sessions,
        )
        for row in rows
    ]


# ── Weekly breakdown ───────────────────────────────────────────────────────────


def get_weekly(
    user: User,
    db: Session,
    date_from: date,
    date_to: date,
) -> list[WeeklyActivity]:
    """
    Week-by-week coding activity for a date range.
    Each week starts on Monday (ISO standard).

    Uses DATE_TRUNC('week', ...) — a PostgreSQL function that truncates a date
    to the Monday of its calendar week.

    Used for: the main productivity trend chart.
    """
    rows = (
        db.query(
            func.date_trunc("week", CodingSession.session_date).label("week_start"),
            func.sum(CodingSession.duration_mins).label("total_mins"),
            func.count(CodingSession.id).label("total_sessions"),
        )
        .filter(
            CodingSession.user_id == user.id,
            CodingSession.session_date >= date_from,
            CodingSession.session_date <= date_to,
        )
        .group_by(text("week_start"))
        .order_by(text("week_start ASC"))
        .all()
    )

    return [
        WeeklyActivity(
            # date_trunc returns a datetime — .date() strips the time component
            week_start=row.week_start.date(),
            total_mins=row.total_mins,
            total_hours=_to_hours(row.total_mins),
            total_sessions=row.total_sessions,
        )
        for row in rows
    ]


# ── Project breakdown ──────────────────────────────────────────────────────────


def get_project_breakdown(
    user: User,
    db: Session,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[ProjectBreakdown]:
    """
    Per-project time breakdown — how many minutes and sessions per project.
    Sessions not linked to a project (project_id=NULL) are excluded.

    Used for: pie charts, donut charts, project comparison bars.
    """
    query = (
        db.query(
            Project.id.label("project_id"),
            Project.title.label("project_title"),
            func.sum(CodingSession.duration_mins).label("total_mins"),
            func.count(CodingSession.id).label("total_sessions"),
        )
        .join(
            # INNER JOIN — only sessions that have a project_id
            Project,
            CodingSession.project_id == Project.id,
        )
        .filter(
            CodingSession.user_id == user.id,
        )
    )

    if date_from:
        query = query.filter(CodingSession.session_date >= date_from)
    if date_to:
        query = query.filter(CodingSession.session_date <= date_to)

    rows = (
        query.group_by(Project.id, Project.title)
        .order_by(text("total_mins DESC"))  # most time spent first
        .all()
    )

    return [
        ProjectBreakdown(
            project_id=row.project_id,
            project_title=row.project_title,
            total_mins=row.total_mins,
            total_hours=_to_hours(row.total_mins),
            total_sessions=row.total_sessions,
        )
        for row in rows
    ]


# ── Streak ─────────────────────────────────────────────────────────────────────


def get_streak(user: User, db: Session) -> StreakData:
    """
    Current and longest coding streak.
    Fetches only the distinct session dates — no full row data.
    """
    date_rows = (
        db.query(CodingSession.session_date)
        .filter(CodingSession.user_id == user.id)
        .distinct()
        .order_by(CodingSession.session_date.desc())
        .all()
    )

    dates = [row.session_date for row in date_rows]
    current_streak, longest_streak = _calculate_streak(dates)

    return StreakData(
        current_streak=current_streak,
        longest_streak=longest_streak,
        last_coded_date=dates[0] if dates else None,
    )
